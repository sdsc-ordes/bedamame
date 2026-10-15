import argparse
import itertools
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse

V3 = "/openbis/openbis/rmi-application-server-v3.json"
RO_CRATE = "/ro-crate-server"
# the only hosts scripts may write to; production changes go through the collaborator
LOCAL_HOSTS = {
    "local.openbis.ch",
    "localhost.openbis.ch",
    "localhost.openbis.net",
    "localhost",
}


def with_ids(value, counter):
    # openBIS 7.0 rejects a JSON object whose only key is @type, so every typed object gets an @id
    if isinstance(value, dict):
        out = {k: with_ids(v, counter) for k, v in value.items()}
        if "@type" in out and "@id" not in out:
            out["@id"] = next(counter)
        return out
    if isinstance(value, list):
        return [with_ids(v, counter) for v in value]
    return value


def resolve(result):
    # responses send an object in full once, then as its @id; swap those ints back for the objects
    by_id, object_keys, seen = {}, set(), set()

    def collect(value):
        if isinstance(value, dict):
            if "@id" in value:
                by_id[value["@id"]] = value
            for k, v in value.items():
                if isinstance(v, dict) or (
                    isinstance(v, list) and any(isinstance(x, dict) for x in v)
                ):
                    object_keys.add(k)
                collect(v)
        elif isinstance(value, list):
            for v in value:
                collect(v)

    def link(value):
        if id(value) in seen:
            return
        seen.add(id(value))
        if isinstance(value, dict):
            for k, v in value.items():
                if k in object_keys and isinstance(v, int) and not isinstance(v, bool):
                    value[k] = by_id.get(v, v)
                elif k in object_keys and isinstance(v, list):
                    value[k] = [by_id.get(x, x) if type(x) is int else x for x in v]
                link(v)
        elif isinstance(value, list):
            for v in value:
                link(v)

    collect(result)
    link(result)
    return result


def request(url: str, headers: dict[str, str], body: bytes | None = None) -> bytes:
    req = urllib.request.Request(
        url, data=body, headers=headers, method="GET" if body is None else "POST"
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


class Openbis:
    def __init__(
        self,
        url: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ):
        self.url = (url or os.environ["OPENBIS_URL"]).rstrip("/")
        self.token = self.rpc(
            "login",
            [
                user or os.environ["OPENBIS_USER"],
                password or os.environ["OPENBIS_PASSWORD"],
            ],
        )

    def rpc(self, method: str, params: list):
        body = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": method,
            "params": with_ids(params, itertools.count(1)),
        }
        try:
            raw = request(
                self.url + V3,
                {"Content-Type": "application/json"},
                json.dumps(body).encode(),
            )
        except urllib.error.HTTPError as e:
            raw = e.read()
        resp = json.loads(raw)
        if "error" in resp:
            raise RuntimeError(f"{method}: {resp['error'].get('message')}")
        return resolve(resp["result"])

    def call(self, method: str, *params):
        return self.rpc(method, [self.token, *params])

    def search(
        self, kind: str, criteria: dict | None = None, fetch: dict | None = None
    ) -> list[dict]:
        # kind is the DTO package, e.g. "space", "sample", "semanticannotation"
        name = {
            "semanticannotation": "SemanticAnnotation",
            "sampletype": "SampleType",
        }.get(kind, kind.title())
        criteria = {
            "@type": f"as.dto.{kind}.search.{name}SearchCriteria",
            **(criteria or {}),
        }
        fetch = {
            "@type": f"as.dto.{kind}.fetchoptions.{name}FetchOptions",
            **(fetch or {}),
        }
        method = {
            "semanticannotation": "searchSemanticAnnotations",
            "sampletype": "searchSampleTypes",
        }.get(kind, f"search{name}s")
        return self.call(method, criteria, fetch)["objects"]

    def require_local(self) -> None:
        if urlparse(self.url).hostname not in LOCAL_HOSTS:
            raise SystemExit(
                f"refusing to write to {self.url}: scripts only write to the local openBIS"
            )

    def upload(self, path: Path) -> None:
        # the session-workspace upload the admin UI uses, as multipart/form-data
        boundary = uuid.uuid4().hex
        fields = {"sessionKeysNumber": "1", "sessionKey_0": "openbis-file-upload", "keepOriginalFileName": "True",
                  "sessionID": self.token}  # fmt: skip
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
            for k, v in fields.items()
        ]
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="openbis-file-upload"; filename="{path.name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n".encode()
            + path.read_bytes()
            + b"\r\n"
        )
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        request(
            self.url + "/openbis/openbis/upload",
            {"Content-Type": f"multipart/form-data; boundary={boundary}"},
            body,
        )

    def import_excel(self, path: Path, mode: str = "UPDATE_IF_EXISTS"):
        # what the admin UI does: upload, then executeImport. mode: UPDATE_IF_EXISTS, IGNORE_EXISTING, FAIL_IF_EXISTS
        self.require_local()
        self.upload(path)
        data = {
            "@type": "as.dto.importer.data.ImportData",
            "format": "EXCEL",
            "sessionWorkspaceFiles": [path.name],
        }
        return self.call(
            "executeImport",
            data,
            {"@type": "as.dto.importer.options.ImportOptions", "mode": mode},
        )

    def export_crate(
        self, identifiers: list[str], fmt: str = "application/ld+json", **options: bool
    ) -> bytes:
        # fmt is application/ld+json (the manifest) or application/zip; options are openBIS export
        # flags, e.g. with_levels_below=True -> openbis.with-levels-below: true. The export runs as a job.
        base = self.url + RO_CRATE
        headers = {
            "api-key": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        flags = {"openbis.send-email": "false"}
        for name, value in options.items():
            flags[
                "openbis." + name.replace("_", "-").replace("datasets", "dataSets")
            ] = str(value).lower()
        body = json.dumps(identifiers).encode()
        job = json.loads(
            request(base + "/export", {**headers, **flags, "Export": fmt}, body)
        )["jobId"]
        while (status := json.loads(request(f"{base}/status/{job}", headers)))[
            "status"
        ] == "RUNNING":
            time.sleep(1)
        if status["status"] != "COMPLETED":
            raise RuntimeError(
                f"RO-Crate export {status['status']}: {status['errors']}"
            )
        return request(
            base + "/download", {"api-key": self.token, "jobid": job, "Accept": "*/*"}
        )


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Log in to openBIS (OPENBIS_URL/USER/PASSWORD) and print what it holds"
    )
    ap.add_argument(
        "--export",
        nargs="+",
        metavar="IDENTIFIER",
        help="export these objects as an RO-Crate manifest",
    )
    ap.add_argument(
        "--out", type=Path, help="where to write the export (default: stdout)"
    )
    args = ap.parse_args()

    o = Openbis()
    if args.export:
        crate = o.export_crate(
            args.export, with_levels_below=True, with_objects_and_datasets_parents=True
        )
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_bytes(crate)
        else:
            sys.stdout.buffer.write(crate)
        return 0

    info = o.call("getServerInformation")
    print(f"{o.url}: openBIS {info['openbis-version']}, API {info['api-version']}")
    print("spaces:", " ".join(sorted(s["code"] for s in o.search("space"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
