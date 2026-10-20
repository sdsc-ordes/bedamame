import argparse
import datetime
import shutil
import sys
import zipfile
from pathlib import Path

from rdflib import RDFS, Graph, URIRef

import config
import openbis_workbook as wb
import validate as v
from openbis_api import Openbis

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "openbis" / "annotated"
COLUMNS = ["Ontology Id", "Ontology Version", "Ontology Annotation Id"]
PLACEHOLDER = "https://example.org/"


def annotation(term: str) -> tuple[str, str, str]:
    ontology_id, version = config.ANNOTATION_SOURCES[term.split(":")[0]]
    return ontology_id, version, config.expand(term)


def present(table: wb.Table, row: list) -> list[tuple]:
    # an exported cell lists one annotation per line
    cells = [str(table.get(row, c) or "") for c in COLUMNS]
    return list(zip(*(c.split("\n") for c in cells))) if cells[0] else []


def unprefix_scripts(types: list[wb.Section]) -> dict[str, str]:
    # openBIS 7.0 imports script X.py as plugin TYPE.X and exports it as TYPE.X.py, so importing an
    # export unchanged makes a new plugin TYPE.TYPE.X. Dropping one prefix keeps the existing plugin.
    renamed = {}
    for s in types:
        row = s.entity.rows[0]
        script = s.entity.get(row, "Validation script") or ""
        if script.startswith(f"{s.code}."):
            renamed[script] = script.removeprefix(f"{s.code}.")
            s.entity.set(row, "Validation script", renamed[script])
    return renamed


def internal(s: wb.Section) -> bool:
    # openBIS 7.0's own PERSON and ORGANIZATION: an import may add fields to them, but not change one
    return s.entity.get(s.entity.rows[0], "Internal") == "TRUE"


def annotate(sections: list[wb.Section], mapping: dict) -> tuple[list, list[dict]]:
    # the 12 Bedretto types must be there; the types the changes add are annotated once they exist.
    # Returns the types to import, without the internal ones, whose missing annotations are "by hand".
    types = [
        s
        for s in sections
        if s.kind == "SAMPLE_TYPE" and s.code in config.ANNOTATED_TYPES
    ]
    missing = set(config.BEDRETTO_TYPES) - {s.code for s in types}
    if missing:
        raise SystemExit(f"not in the export: {', '.join(sorted(missing))}")

    items = []
    for s in types:
        rows = [(s.entity, s.entity.rows[0], "")]
        rows += [(s.children, r, s.children.get(r, "Code")) for r in s.children.rows]
        for table, row, code in rows:
            m = mapping.get((s.code, code.removeprefix("$")))
            if m is None:
                raise SystemExit(f"no row in {config.MAPPING.name} for {s.code} {code}")
            have = present(table, row)
            want = annotation(m["term"]) if m["term"] else None
            # the same term counts as present whatever its Ontology Id and Version: openBIS 7.0's own
            # PERSON annotations use https://schema.org without the slash. The cells then hold that
            # annotation as it is, so that the import leaves it alone.
            same = [h for h in have if want and h[2] == want[2]]
            status = "skip" if not want else "present" if same else "add"
            if status == "add" and internal(s):
                status = "by hand"
            cells = same[0] if same else want or ("", "", "")
            for column, value in zip(COLUMNS, cells):
                table.set(row, column, value)
            label = table.get(row, "Property label") if code else ""
            items.append(
                {
                    "type": s.code,
                    "code": code,
                    "label": label or "",
                    "mapping": m,
                    "status": status,
                    "stale": [h for h in have if not want or h[2] != want[2]],
                }
            )
    return [s for s in types if not internal(s)], items


def note(items: list[dict], export: Path, renamed: dict[str, str]) -> str:
    labels = Graph().parse(v.ONTOLOGY, format="turtle")

    def term(curie: str) -> str:
        label = labels.value(URIRef(config.expand(curie)), RDFS.label)
        return f"{label} (`{curie}`)" if label else f"`{curie}`"

    count = {
        k: sum(i["status"] == k for i in items) for k in ("add", "present", "by hand")
    }
    stale = [i for i in items if i["stale"]]
    lines = [
        "# Semantic annotations for the Bedretto object types",
        "",
        f"Made from `{export.name}` on {datetime.date.today().isoformat()}, "
        f"with Bedretto ontology {config.VERSION}.",
        "",
    ]
    if config.BASE.startswith(PLACEHOLDER):
        lines += [
            f"**Do not import this into production.** The Bedretto terms still use the placeholder "
            f"address `{config.BASE}`; it is for testing on the local openBIS only.",
            "",
        ]
    lines += [
        "## What this does",
        "",
        "It gives each object type, and each field of those types, a link to a term that says "
        "what it means. Nothing else changes: every other cell is copied from your export as it was.",
        "",
        f"- {count['add']} annotations are added;",
        f"- {count['present']} are already there and stay as they are;",
        f"- {count['by hand']} have to be added by hand, listed below;",
        f"- {len(stale)} fields have an annotation that is no longer wanted, listed below.",
        "",
        "Make a fresh master-data export first; this file must be built from it. Then, in the admin "
        "UI: **Tools → Import → All**, choose `annotated.zip`, **Mode: Update if exists**, **Import**.",
        "",
        "An import only adds annotations; it never changes or removes one. To remove an annotation, "
        "open the type in the admin UI and delete it in the field's Semantic Annotations section.",
        "",
    ]
    lines += [
        f"The validation script `{old}` is named `{new}` in this file. openBIS adds the type code "
        "in front of a script name on import, so this keeps the existing script instead of adding "
        "a copy with the code twice.\n"
        for old, new in renamed.items()
    ]
    lines += [
        "Prefixes: "
        + ", ".join(
            f"`{p}:` = `{config.NAMESPACES[p]}`" for p in config.ANNOTATION_SOURCES
        )
        + ".",
        "",
    ]
    by_hand = [i for i in items if i["status"] == "by hand"]
    if by_hand:
        lines += [
            "## Annotations to add by hand",
            "",
            "PERSON and ORGANIZATION come with openBIS; an import may add fields to them but not "
            "change their fields, so it cannot annotate them. In the admin UI, open the type and add "
            "these in the field's Semantic Annotations section:",
            "",
            "| Type | Field | Ontology Id | Ontology Version | Ontology Annotation Id |",
            "|---|---|---|---|---|",
        ]
        for i in by_hand:
            lines.append(
                f"| {i['type']} | {i['code'] or '(the type)'} | "
                + " | ".join(f"`{x}`" for x in annotation(i["mapping"]["term"]))
                + " |"
            )
        lines.append("")
    if stale:
        lines += ["## Annotations to remove by hand", ""]
        for i in stale:
            where = (
                f"{i['type']} field {i['code']}" if i["code"] else f"type {i['type']}"
            )
            for s in i["stale"]:
                lines.append(f"- {where}: `{s[2]}` (version `{s[1]}`)")
        lines.append("")
    for t in dict.fromkeys(i["type"] for i in items):
        rows = [i for i in items if i["type"] == t]
        kind = rows[0]
        lines += [f"## {t}: {term(kind['mapping']['term'])}", ""]
        mapped = [i for i in rows[1:] if i["status"] != "skip"]
        if mapped:
            lines += ["| Field | Code | Means | |", "|---|---|---|---|"]
            for i in mapped:
                lines.append(
                    f"| {i['label']} | `{i['code']}` | {term(i['mapping']['term'])} | {i['status']} |"
                )
            lines.append("")
        skipped = [i for i in rows[1:] if i["status"] == "skip"]
        if skipped:
            lines.append(
                "Not annotated: "
                + "; ".join(
                    f"{i['label']} (`{i['code']}`): {i['mapping']['notes'] or 'not mapped'}"
                    for i in skipped
                )
                + "."
            )
            lines.append("")
    return "\n".join(lines)


def create(o: Openbis, items: list[dict]) -> None:
    # what the collaborator does by hand in the admin UI, through V3 for the local rehearsal
    creations = []
    for i in items:
        entity = {"@type": "as.dto.entitytype.id.EntityTypePermId", "permId": i["type"], "entityKind": "SAMPLE"}  # fmt: skip
        target = (
            {"propertyAssignmentId": {"@type": "as.dto.property.id.PropertyAssignmentPermId", "entityTypeId": entity,
                                      "propertyTypeId": {"@type": "as.dto.property.id.PropertyTypePermId", "permId": i["code"]}}}
            if i["code"]
            else {"entityTypeId": entity}
        )  # fmt: skip
        oid, version, term = annotation(i["mapping"]["term"])
        creations.append({"@type": "as.dto.semanticannotation.create.SemanticAnnotationCreation", **target,
                          "predicateOntologyId": oid, "predicateOntologyVersion": version, "predicateAccessionId": term})  # fmt: skip
    if creations:
        o.require_local()
        o.call("createSemanticAnnotations", creations)


def live(o: Openbis) -> dict[tuple[str, str], list[tuple]]:
    # the annotations in openBIS, keyed like the mapping: (type, property code), "" for the type itself
    fetch = {
        "entityType": {
            "@type": "as.dto.entitytype.fetchoptions.EntityTypeFetchOptions"
        },
        "propertyType": {
            "@type": "as.dto.property.fetchoptions.PropertyTypeFetchOptions"
        },
        "propertyAssignment": {
            "@type": "as.dto.property.fetchoptions.PropertyAssignmentFetchOptions",
            "entityType": {
                "@type": "as.dto.entitytype.fetchoptions.EntityTypeFetchOptions"
            },
            "propertyType": {
                "@type": "as.dto.property.fetchoptions.PropertyTypeFetchOptions"
            },
        },
    }
    out: dict[tuple[str, str], list[tuple]] = {}
    for a in o.search("semanticannotation", fetch=fetch):
        if a.get("entityType"):
            key = (a["entityType"]["code"], "")
        elif a.get("propertyAssignment"):
            pa = a["propertyAssignment"]
            key = (pa["entityType"]["code"], pa["propertyType"]["code"])
        else:
            key = ("*", a["propertyType"]["code"])
        value = tuple(
            a[f"predicate{f}"] for f in ("OntologyId", "OntologyVersion", "AccessionId")
        )
        out.setdefault(key, []).append(value)
    return out


def assignments(o: Openbis) -> dict[str, set[str]]:
    # the sample types in openBIS and their property codes
    fetch = {
        "propertyAssignments": {
            "@type": "as.dto.property.fetchoptions.PropertyAssignmentFetchOptions",
            "propertyType": {
                "@type": "as.dto.property.fetchoptions.PropertyTypeFetchOptions"
            },
        }
    }
    return {
        t["code"]: {pa["propertyType"]["code"] for pa in t["propertyAssignments"]}
        for t in o.search("sampletype", fetch=fetch)
    }


def check(o: Openbis, mapping: dict) -> list[str]:
    # compares term IRIs; mapping rows for types or fields not in openBIS (yet) are left out
    have, types = live(o), assignments(o)
    problems = []
    for (t, code), m in mapping.items():
        if t not in types or (code and code not in types[t]):
            continue
        got = sorted(a[2] for a in have.get((t, code), []))
        want = [config.expand(m["term"])] if m["term"] else []
        if got != want:
            problems.append(f"{t} {code or '(type)'}: has {got}, mapping says {want}")
    codes = {code for _, code in mapping if code}
    problems += [
        f"property {code}: annotated as a property type, {have[('*', code)]}"
        for code in sorted(codes)
        if ("*", code) in have
    ]
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Annotate the Bedretto object types in a fresh openBIS master-data export"
    )
    ap.add_argument(
        "export",
        type=Path,
        nargs="?",
        help="object-types.xlsx from a master-data export",
    )
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help="import the result into the local openBIS",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="compare the annotations in openBIS (OPENBIS_URL) with the mapping; reads only",
    )
    args = ap.parse_args()

    if args.check:
        problems = check(Openbis(), config.load_mapping())
        print("\n".join(problems) or "annotations agree with the mapping")
        return 1 if problems else 0
    if not args.export:
        ap.error("give an export, or --check")

    types, items = annotate(wb.read(args.export), config.load_mapping())
    renamed = unprefix_scripts(types)
    if args.out.exists():
        shutil.rmtree(args.out)
    wb.write(types, args.out / "masterdata.xlsx")
    scripts = args.export.parent / "scripts"
    if scripts.is_dir():
        (args.out / "scripts").mkdir()
        for f in scripts.iterdir():
            shutil.copy(f, args.out / "scripts" / renamed.get(f.name, f.name))
    with zipfile.ZipFile(args.out / "annotated.zip", "w") as z:
        z.write(args.out / "masterdata.xlsx", "masterdata.xlsx")
        for f in sorted((args.out / "scripts").glob("*")):
            z.write(f, f"scripts/{f.name}")
    (args.out / "annotations-changes.md").write_text(note(items, args.export, renamed))
    added = sum(i["status"] == "add" for i in items)
    by_hand = [i for i in items if i["status"] == "by hand"]
    print(f"{args.out}: {added} to add, {len(by_hand)} by hand, "
          f"{sum(bool(i['stale']) for i in items)} stale")  # fmt: skip

    if args.do_import:
        o = Openbis()
        o.import_excel(args.out / "annotated.zip")
        create(o, by_hand)
        print("imported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
