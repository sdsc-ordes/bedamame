import argparse
import csv
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
MAPPING = ROOT / "mapping" / "openbis-annotations.csv"
OUT = ROOT / "out" / "openbis" / "annotated"
COLUMNS = ["Ontology Id", "Ontology Version", "Ontology Annotation Id"]
PLACEHOLDER = "https://example.org/"


def load_mapping(path: Path = MAPPING) -> dict[tuple[str, str], dict]:
    with path.open() as f:
        return {(r["object_type"], r["property_code"]): r for r in csv.DictReader(f)}


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


def annotate(sections: list[wb.Section], mapping: dict) -> tuple[list, list[dict]]:
    types = [
        s
        for s in sections
        if s.kind == "SAMPLE_TYPE" and s.code in config.BEDRETTO_TYPES
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
                raise SystemExit(f"no row in {MAPPING.name} for {s.code} {code}")
            have = present(table, row)
            want = annotation(m["term"]) if m["term"] else None
            if want:
                for column, value in zip(COLUMNS, want):
                    table.set(row, column, value)
            label = table.get(row, "Property label") if code else ""
            items.append(
                {
                    "type": s.code,
                    "code": code,
                    "label": label or "",
                    "mapping": m,
                    "status": (
                        "skip" if not want else "present" if want in have else "add"
                    ),
                    "stale": [h for h in have if h != want],
                }
            )
    return types, items


def note(items: list[dict], export: Path, renamed: dict[str, str]) -> str:
    labels = Graph().parse(v.ONTOLOGY, format="turtle")

    def term(curie: str) -> str:
        label = labels.value(URIRef(config.expand(curie)), RDFS.label)
        return f"{label} (`{curie}`)" if label else f"`{curie}`"

    count = {k: sum(i["status"] == k for i in items) for k in ("add", "present")}
    stale = [i for i in items if i["stale"]]
    lines = [
        "# Semantic annotations for the 12 Bedretto object types",
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


def check(o: Openbis, mapping: dict) -> list[str]:
    have = live(o)
    problems = []
    for (t, code), m in mapping.items():
        got = sorted(have.get((t, code), []))
        want = [annotation(m["term"])] if m["term"] else []
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
        description="Annotate the 12 Bedretto object types in a fresh openBIS master-data export"
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
        problems = check(Openbis(), load_mapping())
        print("\n".join(problems) or "annotations agree with the mapping")
        return 1 if problems else 0
    if not args.export:
        ap.error("give an export, or --check")

    types, items = annotate(wb.read(args.export), load_mapping())
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
    print(f"{args.out}: {added} to add, {sum(bool(i['stale']) for i in items)} stale")

    if args.do_import:
        Openbis().import_excel(args.out / "annotated.zip")
        print("imported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
