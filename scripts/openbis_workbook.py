import argparse
import shutil
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook, load_workbook

from openbis_api import Openbis

warnings.filterwarnings("ignore", module="openpyxl")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "openbis" / "masterdata-import"

BEDRETTO_TYPES = [
    "BOREHOLES", "BOREHOLE_LOGGING",
    "CORES", "CORE_REQUEST", "IGSN_CORE",
    "SENSORS", "SEIS_SENSOR", "SENSOR_INSTAL", "SEIS_SENSOR_INSTAL",
    "DATALOGGER", "DEVICE", "METHOD",
]  # fmt: skip

# sections with one entity row followed by a table of terms or property assignments
WITH_CHILDREN = {"VOCABULARY_TYPE", "SAMPLE_TYPE", "EXPERIMENT_TYPE", "DATASET_TYPE"}
# export-only columns, and Unique Subcodes, which the 7.0 import rejects
DROP = ["Registrator", "Registration Date", "Modification Date", "Unique Subcodes"]
# internal in 7.0 although the export has them without $
INTERNAL_IN_70 = {"PRODUCT.DESCRIPTION"}
PROPERTY_TYPE_COLUMNS = ["Property label", "Description", "Data type", "Vocabulary code", "Metadata"]


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
        return self.entity.get(self.entity.rows[0], "Code")


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
                defs.setdefault(code[1:], [t.children.get(row, c) for c in PROPERTY_TYPE_COLUMNS])
    for t in types:
        for row in t.children.rows:
            code = t.children.get(row, "Code")
            plain = code.removeprefix("$")
            t.children.set(row, "Code", plain)
            t.children.set(row, "Internal", "TRUE" if plain in defs or plain in INTERNAL_IN_70 else "FALSE")
            own = [t.children.get(row, c) for c in PROPERTY_TYPE_COLUMNS]
            if plain in defs and own != defs[plain]:
                print(f"{t.code}.{plain}: takes the definition of ${plain}, was {own}")
                for c, v in zip(PROPERTY_TYPE_COLUMNS, defs[plain]):
                    t.children.set(row, c, v)


def import_subset(sections: list[Section]) -> list[Section]:
    # 7.0 ships the ELN defaults and the $ vocabularies; keep the Bedretto types and what they use
    types = [s for s in sections if s.kind == "SAMPLE_TYPE" and s.code in BEDRETTO_TYPES]
    vocabs = used_vocabularies(types)
    keep = [s for s in sections if s.kind == "VOCABULARY_TYPE" and s.code in vocabs and not s.code.startswith("$")]
    keep += sorted(types, key=lambda t: BEDRETTO_TYPES.index(t.code))
    for s in keep:
        if s.entity.get(s.entity.rows[0], "Unique Subcodes") not in (None, "FALSE"):
            print(f"warning: {s.code} has Unique Subcodes set; the 7.0 import drops it")
        for name in DROP:
            s.entity.drop(name)
    internal_to_70([s for s in keep if s.kind == "SAMPLE_TYPE"])
    return keep

def main() -> int:
    ap = argparse.ArgumentParser(description="Build an importable master-data folder from an openBIS export")
    ap.add_argument("export", type=Path, help="object-types.xlsx from an openBIS master-data export")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--import", dest="do_import", action="store_true", help="import the zip into the local openBIS")
    args = ap.parse_args()

    sections = import_subset(read(args.export))
    missing = set(BEDRETTO_TYPES) - {s.code for s in sections}
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
    print(f"{args.out}.zip: {len(sections) - len(vocabs)} types, {len(vocabs)} vocabularies ({', '.join(vocabs)})")
    if args.do_import:
        Openbis().import_excel(Path(f"{args.out}.zip"))
        print("imported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
