import argparse
import shutil
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook, load_workbook

import config

from openbis_api import Openbis

warnings.filterwarnings("ignore", module="openpyxl")

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out" / "openbis" / "masterdata-import"

# sections with one entity row followed by a table of terms, property assignments or objects
WITH_CHILDREN = {
    "VOCABULARY_TYPE",
    "SAMPLE_TYPE",
    "EXPERIMENT_TYPE",
    "DATASET_TYPE",
    "SAMPLE",
    "EXPERIMENT",
}
# export-only columns, and Unique Subcodes, which the 7.0 import rejects
DROP = ["Registrator", "Registration Date", "Modification Date", "Unique Subcodes"]
# internal in 7.0 although the export has them without $
INTERNAL_IN_70 = {"PRODUCT.DESCRIPTION"}
PROPERTY_TYPE_COLUMNS = [
    "Property label",
    "Description",
    "Data type",
    "Vocabulary code",
    "Metadata",
]


@dataclass
class Table:
    header: list[str]
    rows: list[list]

    def get(self, row: list, name: str):
        i = self.header.index(name) if name in self.header else len(row)
        return row[i] if i < len(row) else None

    def set(self, row: list, name: str, value) -> None:
        if name not in self.header:
            self.header.append(name)
        i = self.header.index(name)
        row.extend([None] * (i + 1 - len(row)))
        row[i] = value

    def drop(self, name: str) -> None:
        if name in self.header:
            i = self.header.index(name)
            del self.header[i]
            for row in self.rows:
                del row[i : i + 1]


@dataclass
class Section:
    kind: str
    entity: Table
    children: Table | None

    @property
    def code(self) -> str:
        return self.entity.rows[0][0]


def trim(row) -> list:
    row = list(row)
    while row and row[-1] in (None, ""):
        row.pop()
    return row


def parse(block: list[list]) -> Section:
    if block[0][0] in WITH_CHILDREN:
        children = Table(block[3], block[4:]) if len(block) > 3 else None
        return Section(block[0][0], Table(block[1], [block[2]]), children)
    return Section(block[0][0], Table(block[1], block[2:]), None)


def read(path: Path) -> list[Section]:
    sections, block = [], []
    for row in load_workbook(path).worksheets[0].iter_rows(values_only=True):
        if row := trim(row):
            block.append(row)
        elif block:
            sections.append(parse(block))
            block = []
    if block:
        sections.append(parse(block))
    return sections


def write(sections: list[Section], path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    for s in sections:
        ws.append([s.kind])
        for row in [s.entity.header, *s.entity.rows]:
            ws.append(row)
        if s.children:
            for row in [s.children.header, *s.children.rows]:
                ws.append(row)
        ws.append([])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


TYPE_HEADER = [
    "Code",
    "Internal",
    "Description",
    "Auto generate codes",
    "Validation script",
    "Generated code prefix",
]
PROPERTY_HEADER = [
    "Code",
    "Internal",
    "Mandatory",
    "Show in edit views",
    "Section",
    "Property label",
    "Data type",
    "Vocabulary code",
    "Description",
    "Metadata",
    "Dynamic script",
    "Multivalued",
    "Unique",
    "Pattern",
    "Pattern Type",
    "Internal Assignment",
]
ATTRIBUTES = [
    "$",
    "Auto generate code",
    "Identifier",
    "Code",
    "Space",
    "Project",
    "Experiment",
    "Parents",
    "Children",
]


def flag(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def sample_type(
    code: str, description: str, prefix: str, properties: list[list], internal=False
) -> Section:
    row = [code, flag(internal), description, "FALSE", "", prefix]
    return Section(
        "SAMPLE_TYPE",
        Table(list(TYPE_HEADER), [row]),
        Table(list(PROPERTY_HEADER), properties),
    )


def property_row(
    code: str,
    label: str,
    data_type: str,
    description: str,
    section: str = "General",
    vocabulary: str = "",
    multivalued: bool = False,
    internal: bool = False,
) -> list:
    return [code, flag(internal), "FALSE", "TRUE", section, label, data_type, vocabulary, description,
            "", "", flag(multivalued), "FALSE", "", "", "FALSE"]  # fmt: skip


def vocabulary(
    code: str, description: str, terms: list[tuple[str, str, str]]
) -> Section:
    rows = [[c, "FALSE", label, text] for c, label, text in terms]
    return Section(
        "VOCABULARY_TYPE",
        Table(["Code", "Internal", "Description"], [[code, "FALSE", description]]),
        Table(["Code", "Internal", "Label", "Description"], rows),
    )


def spaces(codes: dict[str, str]) -> Section:
    return Section(
        "SPACE",
        Table(["Code", "Description"], [[c, d] for c, d in codes.items()]),
        None,
    )


def projects(identifiers: list[str]) -> Section:
    rows = [[p, p.rsplit("/", 1)[1], p.split("/")[1]] for p in identifiers]
    return Section("PROJECT", Table(["Identifier", "Code", "Space"], rows), None)


def collections(names: dict[str, str]) -> Section:
    rows = [[c, c.rsplit("/", 1)[1], c.rsplit("/", 1)[0], n] for c, n in names.items()]
    return Section(
        "EXPERIMENT",
        Table(["Experiment type"], [["COLLECTION"]]),
        Table(["Identifier", "Code", "Project", "NAME"], rows),
    )


def samples(sample_type: str, objects: list[dict], codes: list[str]) -> Section:
    # objects: identifier, plus collection for new ones, parents, and properties by code
    rows = []
    for o in objects:
        ident = o["identifier"]
        project, collection = ident.rsplit("/", 1)[0], o.get("collection", "")
        rows.append(["", "FALSE", ident, ident.rsplit("/", 1)[1], ident.split("/")[1], project,
                     collection, "\n".join(o.get("parents", [])), ""]
                    + [o["properties"].get(c, "") for c in codes])  # fmt: skip
    return Section(
        "SAMPLE",
        Table(["Sample type"], [[sample_type]]),
        Table(ATTRIBUTES + codes, rows),
    )


def assignment_codes(masterdata: list[Section]) -> dict[str, list[str]]:
    return {
        s.code: [s.children.get(r, "Code").removeprefix("$") for r in s.children.rows]
        for s in masterdata
        if s.kind == "SAMPLE_TYPE" and s.children
    }


def read_objects(path: Path, masterdata: list[Section]) -> list[dict]:
    # object exports head their property columns with labels, which repeat ("Project" is an attribute
    # and a property); the columns follow the type's assignments in order, so map them by position
    codes = assignment_codes(masterdata)
    out = []
    for s in read(path):
        if s.kind != "SAMPLE" or not s.children:
            continue
        header = s.children.header
        last = "Meta Data" if "Meta Data" in header else "Children"
        first = header.index(last) + 1
        props = codes[s.code]
        if len(header) - first != len(props):
            raise SystemExit(
                f"{path.name}: {len(header) - first} property columns, {s.code} has {len(props)}"
            )
        for row in s.children.rows:
            row = list(row) + [None] * (len(header) - len(row))
            out.append(
                {
                    "type": s.code,
                    "identifier": row[header.index("Identifier")],
                    "collection": row[header.index("Experiment")] or "",
                    "parents": [
                        p for p in (row[header.index("Parents")] or "").split("\n") if p
                    ],
                    "properties": {
                        c: str(v)
                        for c, v in zip(props, row[first:])
                        if v not in (None, "")
                    },
                }
            )
    return out


def used_vocabularies(types: list[Section]) -> set[str]:
    return {
        t.children.get(row, "Vocabulary code")
        for t in types
        if t.children
        for row in t.children.rows
        if t.children.get(row, "Vocabulary code")
    }


def internal_to_70(types: list[Section]) -> None:
    # 7.0 dropped the $ of internal properties ($NAME is NAME) and flags them Internal instead; without
    # the flag the import tries to update them, which only the system user may do. Where the lab also
    # had a plain property of the same code, those rows take the internal definition, since one sheet
    # may declare a code only once.
    defs = {}
    for t in types:
        for row in t.children.rows:
            if (code := t.children.get(row, "Code")).startswith("$"):
                defs.setdefault(
                    code[1:], [t.children.get(row, c) for c in PROPERTY_TYPE_COLUMNS]
                )
    for t in types:
        for row in t.children.rows:
            code = t.children.get(row, "Code")
            plain = code.removeprefix("$")
            t.children.set(row, "Code", plain)
            t.children.set(
                row,
                "Internal",
                "TRUE" if plain in defs or plain in INTERNAL_IN_70 else "FALSE",
            )
            own = [t.children.get(row, c) for c in PROPERTY_TYPE_COLUMNS]
            if plain in defs and own != defs[plain]:
                print(f"{t.code}.{plain}: takes the definition of ${plain}, was {own}")
                for c, v in zip(PROPERTY_TYPE_COLUMNS, defs[plain]):
                    t.children.set(row, c, v)


def import_subset(sections: list[Section]) -> list[Section]:
    # 7.0 ships the ELN defaults and the $ vocabularies; keep the Bedretto types and what they use
    types = [
        s
        for s in sections
        if s.kind == "SAMPLE_TYPE" and s.code in config.BEDRETTO_TYPES
    ]
    vocabs = used_vocabularies(types)
    keep = [
        s
        for s in sections
        if s.kind == "VOCABULARY_TYPE"
        and s.code in vocabs
        and not s.code.startswith("$")
    ]
    keep += sorted(types, key=lambda t: config.BEDRETTO_TYPES.index(t.code))
    for s in keep:
        if s.entity.get(s.entity.rows[0], "Unique Subcodes") not in (None, "FALSE"):
            print(f"warning: {s.code} has Unique Subcodes set; the 7.0 import drops it")
        for name in DROP:
            s.entity.drop(name)
    internal_to_70([s for s in keep if s.kind == "SAMPLE_TYPE"])
    return keep


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build an importable master-data folder from an openBIS export"
    )
    ap.add_argument(
        "export", type=Path, help="object-types.xlsx from an openBIS master-data export"
    )
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help="import the zip into the local openBIS",
    )
    args = ap.parse_args()

    sections = import_subset(read(args.export))
    missing = set(config.BEDRETTO_TYPES) - {s.code for s in sections}
    if missing:
        print("missing types:", ", ".join(sorted(missing)))
        return 1

    if args.out.exists():
        shutil.rmtree(args.out)
    write(sections, args.out / "masterdata.xlsx")
    scripts = args.export.parent / "scripts"
    if scripts.is_dir():
        shutil.copytree(scripts, args.out / "scripts")
    shutil.make_archive(str(args.out), "zip", args.out)

    vocabs = [s.code for s in sections if s.kind == "VOCABULARY_TYPE"]
    print(
        f"{args.out}.zip: {len(sections) - len(vocabs)} types, {len(vocabs)} vocabularies ({', '.join(vocabs)})"
    )
    if args.do_import:
        Openbis().import_excel(Path(f"{args.out}.zip"))
        print("imported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
