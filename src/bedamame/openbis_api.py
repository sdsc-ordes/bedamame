import argparse
import datetime
import io
import itertools
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import config

V3 = "/openbis/openbis/rmi-application-server-v3.json"
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


# objects that describe another object, and the link to it: a dump takes them along with that object
DESCRIBING = {"BOREHOLE_MOUTH_SURVEY": "BOREHOLE", "SENSOR_POSITION": "INSTALLATION"}
# openBIS's own accounts, kept by name when a dump is anonymised
ACCOUNTS = {"admin", "system"}


def fetch(name: str, package: str = "", **more) -> dict:
    # V3 fetch options, e.g. fetch("Sample", properties=fetch("Property", "property"))
    package = package or name.lower()
    return {"@type": f"as.dto.{package}.fetchoptions.{name}FetchOptions", **more}


def type_criteria(sample_types: list[str]) -> dict:
    return {
        "@type": "as.dto.sample.search.SampleSearchCriteria",
        "operator": "OR",
        "criteria": [
            {
                "@type": "as.dto.sample.search.SampleTypeSearchCriteria",
                "criteria": [
                    {
                        "@type": "as.dto.common.search.CodeSearchCriteria",
                        "fieldValue": {
                            "@type": "as.dto.common.search.StringEqualToValue",
                            "value": t,
                        },
                    }
                ],
            }
            for t in sample_types
        ],
    }


def iso(ms: int | None) -> str | None:
    # V3 dates are milliseconds since 1970
    if ms is None:
        return None
    t = datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def anonymise(dump: dict) -> dict:
    # for a dump that goes into git: fields without an annotation are dropped (the free-text names among
    # them), people become Person 1, 2, ... and accounts other than openBIS's own become user-1, 2, ...
    people = sorted(
        (o for o in dump["objects"] if o["type"] == "PERSON"), key=lambda o: o["permId"]
    )
    for o in dump["objects"]:
        props = dump["types"][o["type"]]["properties"]
        o["properties"] = {
            c: v for c, v in o["properties"].items() if props[c]["annotations"]
        }
    for i, o in enumerate(people, 1):
        o["code"] = f"PERSON_{i}"
        o["identifier"] = f"{o['identifier'].rsplit('/', 1)[0]}/{o['code']}"
        links = {c: v for c, v in o["properties"].items() if dump["types"]["PERSON"]["properties"][c]["dataType"] == "SAMPLE"}  # fmt: skip
        o["properties"] = {"NAME": f"Person {i}", **links}
    others = sorted(u for u in dump["users"] if u not in ACCOUNTS)
    names = {u: u for u in dump["users"] if u in ACCOUNTS}
    names |= {u: f"user-{i}" for i, u in enumerate(others, 1)}
    for record in [*dump["objects"], *dump["collections"].values()]:
        for key in ("registrator", "modifier"):
            if record.get(key):
                record[key] = names[record[key]]
    dump["users"] = {names[u]: {"name": names[u]} for u in dump["users"]}
    return dump


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
        try:
            resp = json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError(f"{method}: not a JSON-RPC response: {raw[:200]!r}")
        if "error" in resp:
            raise RuntimeError(f"{method}: {resp['error'].get('message')}")
        return resolve(resp["result"])

    def call(self, method: str, *params):
        return self.rpc(method, [self.token, *params])

    def search(
        self, kind: str, criteria: dict | None = None, fetch: dict | None = None
    ) -> list[dict]:
        # kind names the DTO, e.g. "space", "sample", "sampletype", "semanticannotation"
        name = {
            "semanticannotation": "SemanticAnnotation",
            "sampletype": "SampleType",
        }.get(kind, kind.title())
        package = {"sampletype": "sample"}.get(kind, kind)
        criteria = {
            "@type": f"as.dto.{package}.search.{name}SearchCriteria",
            **(criteria or {}),
        }
        fetch = {
            "@type": f"as.dto.{package}.fetchoptions.{name}FetchOptions",
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

    def export_masterdata(self, sample_types: list[str], out: Path) -> Path:
        # the admin UI's import-compatible export: object-types.xlsx, with the vocabularies the types use,
        # and the scripts/ folder of their validation scripts; types not in openBIS (yet) are left out
        existing = {t["code"] for t in self.search("sampletype")}
        sample_types = [t for t in sample_types if t in existing]
        data = {
            "@type": "as.dto.exporter.data.ExportData",
            "permIds": [
                {
                    "@type": "as.dto.exporter.data.ExportablePermId",
                    "exportableKind": "SAMPLE_TYPE",
                    "permId": t,
                }
                for t in sample_types
            ],
            "fields": {"@type": "as.dto.exporter.data.AllFields"},
        }
        options = {
            "@type": "as.dto.exporter.options.ExportOptions",
            "formats": ["XLSX"],
            "xlsTextFormat": "PLAIN",
            "withReferredTypes": True,
            "withImportCompatibility": True,
            "zipSingleFiles": False,
        }
        url = self.call("executeExport", data, options)["downloadURL"]
        body = request(url, {})
        out.mkdir(parents=True, exist_ok=True)
        if url.endswith(".xlsx"):
            (out / "object-types.xlsx").write_bytes(body)
            return out / "object-types.xlsx"
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            for name in z.namelist():
                if name.endswith(".xlsx"):
                    (out / "object-types.xlsx").write_bytes(z.read(name))
                elif "/scripts/" in f"/{name}" and not name.endswith("/"):
                    target = out / "scripts" / Path(name).name
                    target.parent.mkdir(exist_ok=True)
                    target.write_bytes(z.read(name))
        return out / "object-types.xlsx"

    def export_objects(self, sample_types: list[str], out: Path) -> Path:
        # every object of these types, in the import-compatible format of an ELN export
        found = self.search("sample", type_criteria(sample_types))
        perm_ids = [s["permId"]["permId"] for s in found]
        if not perm_ids:
            return out
        data = {
            "@type": "as.dto.exporter.data.ExportData",
            "permIds": [
                {
                    "@type": "as.dto.exporter.data.ExportablePermId",
                    "exportableKind": "SAMPLE",
                    "permId": p,
                }
                for p in perm_ids
            ],
            "fields": {"@type": "as.dto.exporter.data.AllFields"},
        }
        options = {
            "@type": "as.dto.exporter.options.ExportOptions",
            "formats": ["XLSX"],
            "xlsTextFormat": "PLAIN",
            "withReferredTypes": False,
            "withImportCompatibility": True,
            "zipSingleFiles": False,
        }
        url = self.call("executeExport", data, options)["downloadURL"]
        body = request(url, {})
        out.parent.mkdir(parents=True, exist_ok=True)
        if not url.endswith(".xlsx"):
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                body = z.read(next(n for n in z.namelist() if n.endswith(".xlsx")))
        out.write_bytes(body)
        return out

    def dump(self, sample_types: list[str], select: list[str] | None = None) -> dict:
        # what openbis_to_rdf.py reads: objects with their properties by code (links as permIds),
        # registrator, modifier and dates; their types' data types and annotations; collection names.
        # select: collection or object identifiers; those objects, what they link to, what describes them
        annotations = fetch("SemanticAnnotation")
        types = {
            t["code"]: t
            for t in self.search("sampletype", fetch=fetch(
                "SampleType", "sample", semanticAnnotations=annotations,
                propertyAssignments=fetch("PropertyAssignment", "property", semanticAnnotations=annotations,
                                          propertyType=fetch("PropertyType", "property", vocabulary=fetch("Vocabulary"))),
            ))
            if t["code"] in sample_types
        }  # fmt: skip
        person = fetch("Person")
        samples = self.search("sample", type_criteria(list(types)), fetch(
            "Sample", type=fetch("SampleType", "sample"), properties=fetch("Property", "property"),
            registrator=person, modifier=person, space=fetch("Space"), project=fetch("Project"),
            experiment=fetch("Experiment", properties=fetch("Property", "property"), registrator=person),
        ))  # fmt: skip
        data_types = {
            (code, pa["propertyType"]["code"]): pa["propertyType"]["dataType"]
            for code, t in types.items()
            for pa in t["propertyAssignments"]
        }
        by_perm = {s["permId"]["permId"]: s for s in samples}
        if select:
            chosen = {
                p
                for p, s in by_perm.items()
                if s["identifier"]["identifier"] in select
                or (
                    s["experiment"]
                    and s["experiment"]["identifier"]["identifier"] in select
                )
            }
            while True:
                more = {
                    link
                    for p in chosen
                    for code, value in by_perm[p]["properties"].items()
                    if data_types[(by_perm[p]["type"]["code"], code)] == "SAMPLE"
                    for link in as_list(value)
                    if link in by_perm
                } | {
                    p
                    for p, s in by_perm.items()
                    if s["properties"].get(DESCRIBING.get(s["type"]["code"])) in chosen
                }
                if more <= chosen:
                    break
                chosen |= more
            samples = [s for p, s in by_perm.items() if p in chosen]

        out = {"types": {}, "collections": {}, "users": {}, "objects": []}

        def user(p: dict | None) -> str | None:
            if p:
                name = " ".join(filter(None, (p.get("firstName"), p.get("lastName"))))
                out["users"][p["userId"]] = {"name": name or p["userId"]}
                return p["userId"]
            return None

        for s in sorted(samples, key=lambda s: s["identifier"]["identifier"]):
            e = s["experiment"]
            out["objects"].append({
                "permId": s["permId"]["permId"], "identifier": s["identifier"]["identifier"],
                "code": s["code"], "type": s["type"]["code"],
                "space": s["space"]["code"] if s["space"] else None,
                "project": s["project"]["identifier"]["identifier"] if s["project"] else None,
                "collection": e["identifier"]["identifier"] if e else None,
                "properties": s["properties"],
                "registrator": user(s["registrator"]), "modifier": user(s["modifier"]),
                "registrationDate": iso(s["registrationDate"]), "modificationDate": iso(s["modificationDate"]),
            })  # fmt: skip
            if e:
                out["collections"][e["identifier"]["identifier"]] = {
                    "permId": e["permId"]["permId"], "name": e["properties"].get("NAME"),
                    "registrator": user(e["registrator"]),
                    "registrationDate": iso(e["registrationDate"]), "modificationDate": iso(e["modificationDate"]),
                }  # fmt: skip
        for code in sorted({o["type"] for o in out["objects"]}):
            t = types[code]
            out["types"][code] = {
                "annotations": [a["predicateAccessionId"] for a in t["semanticAnnotations"]],
                "properties": {
                    pa["propertyType"]["code"]: {
                        "dataType": pa["propertyType"]["dataType"],
                        "vocabulary": (pa["propertyType"]["vocabulary"] or {}).get("code"),
                        "multiValue": pa["propertyType"]["multiValue"],
                        "annotations": [a["predicateAccessionId"] for a in pa["semanticAnnotations"]],
                    }
                    for pa in t["propertyAssignments"]
                },
            }  # fmt: skip
        return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Log in to openBIS (OPENBIS_URL/USER/PASSWORD) and print what it holds"
    )
    ap.add_argument(
        "--masterdata",
        type=Path,
        metavar="DIR",
        help="export the master data of the Bedretto object types to DIR",
    )
    ap.add_argument(
        "--dump",
        type=Path,
        metavar="FILE",
        help="dump the objects of the Bedretto types to FILE as JSON, for openbis_to_rdf.py",
    )
    ap.add_argument(
        "--select",
        nargs="+",
        metavar="IDENTIFIER",
        help="with --dump: only these collections and objects, what they link to, what describes them",
    )
    ap.add_argument(
        "--anonymise",
        action="store_true",
        help="with --dump: drop fields without an annotation, replace people's and users' names",
    )
    args = ap.parse_args()

    o = Openbis()
    if args.dump:
        dump = o.dump(config.ANNOTATED_TYPES, args.select)
        if args.anonymise:
            dump = anonymise(dump)
        args.dump.parent.mkdir(parents=True, exist_ok=True)
        args.dump.write_text(json.dumps(dump, indent=1, ensure_ascii=False) + "\n")
        print(f"{args.dump}: {len(dump['objects'])} objects")
        return 0
    if args.masterdata:
        print(o.export_masterdata(config.ANNOTATED_TYPES, args.masterdata))
        return 0

    info = o.call("getServerInformation")
    print(f"{o.url}: openBIS {info['openbis-version']}, API {info['api-version']}")
    print("spaces:", " ".join(sorted(s["code"] for s in o.search("space"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
