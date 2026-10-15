import argparse
import csv
import re
import sys
import warnings
from pathlib import Path

from openpyxl import Workbook, load_workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import openbis_workbook as wb  # noqa: E402
from openbis_api import Openbis  # noqa: E402

warnings.filterwarnings("ignore", module="openpyxl")

LAB = ROOT / "drive-files" / "openBIS-20261006T123341Z-1-001" / "openBIS"
CSV = ROOT / "drive-files" / "CSV"
OUT = ROOT / "out" / "openbis" / "seed.xlsx"

OBJECT_EXPORTS = [
    "objects.2026-09-08-sensor-inventory/sensor-inventory.xlsx",
    "objects.2026-09-08-sensor-installation/sensor-installation.xlsx",
    "objects.2026-09-08-seismic-sensor-installation/seismic_sensor_installation.xlsx",
    "objects.2026-09-08-20-borehole-logging.xlsx",
]
# file and widget content that does not travel with the export
BLANK = {"DOCUMENT", "XMLCOMMENTS", "GENERAL_PROTOCOL.SPREADSHEET"}
DROP_PARENTS = {"/INFRASTRUCTURE/BOREHOLES/WELLTEC"}

SPACES = {"INFRASTRUCTURE": "Boreholes and logging", "09_FEAR": "FEAR experiments", "EQUIPMENT": "Sensors and devices"}
PROJECTS = ["/INFRASTRUCTURE/BOREHOLES", "/09_FEAR/06_FEAR2", "/EQUIPMENT/SENSOR_CATALOG"]
# the lab's borehole collection is unknown (see collaborator-requests.md); BOREHOLES stands in for it
COLLECTIONS = {
    "/INFRASTRUCTURE/BOREHOLES/BOREHOLES": "Boreholes",
    "/INFRASTRUCTURE/BOREHOLES/04_ROCK_PROPERTIES_EXP_3": "Rock properties experiment 3",
    "/09_FEAR/06_FEAR2/F2_INSTALLATION": "FEAR-2 installation",
    "/09_FEAR/06_FEAR2/F2_INSTALLATION_SEIS": "FEAR-2 seismic installation",
    "/EQUIPMENT/SENSOR_CATALOG/TILTMETERS": "Tilt meters",
    "/EQUIPMENT/SENSOR_CATALOG/SEISMIC_SENSORS": "Seismic sensors",
    "/EQUIPMENT/SENSOR_CATALOG/DEVICES": "Devices",
}
STUB = "stub: referenced by the lab export but not in it"

ATTRIBUTES = ["$", "Auto generate code", "Identifier", "Code", "Space", "Project", "Experiment", "Parents", "Children"]


def assignment_codes(masterdata: Path) -> dict[str, list[str]]:
    return {
        s.code: [s.children.get(row, "Code").removeprefix("$") for row in s.children.rows]
        for s in wb.read(masterdata)
        if s.kind == "SAMPLE_TYPE" and s.code in wb.BEDRETTO_TYPES
    }


def objects(collection: str, rows: list[dict]) -> list[list]:
    space, project = collection.split("/")[1], collection.rsplit("/", 1)[0]
    out = []
    for r in rows:
        code = r.pop("code")
        out.append(["", "FALSE", f"{project}/{code}", code, space, project, collection, "", "", r])
    return out

def from_export(path: Path, codes: dict[str, list[str]]) -> tuple[str, list[list]]:
    # property columns follow the type's assignments in order; the headers are labels, so map by position
    rows = [list(r) for r in load_workbook(path).worksheets[0].iter_rows(values_only=True)]
    sample_type, header = rows[2][0], wb.trim(rows[3])
    props = codes[sample_type]
    first = header.index("Children") + 1
    if len(header) - first != len(props):
        raise SystemExit(f"{path.name}: {len(header) - first} property columns, {sample_type} has {len(props)}")
    out = []
    for row in rows[4:]:
        if not any(row):
            continue
        row = list(row) + [None] * (len(header) - len(row))
        attrs = dict(zip(ATTRIBUTES, row[:first]))
        values = {p: ("" if p in BLANK else row[first + i]) for i, p in enumerate(props)}
        parents = [p for p in (attrs["Parents"] or "").split("\n") if p and p not in DROP_PARENTS]
        out.append([*row[:first][:7], "\n".join(parents), "", values])
    return sample_type, out


def boreholes(path: Path, coords: Path) -> list[dict]:
    coord = {c["coord_id"]: c for c in csv.DictReader(coords.open(encoding="utf-8-sig"))}
    out = []
    for b in csv.DictReader(path.open(encoding="utf-8-sig")):
        c = coord.get(b["coord_id"], {})
        out.append({
            "code": b["borehole_name"],
            "BOREHOLE_NAME": b["borehole_name"],
            "BOREHOLE_NICKNAME": b["nickname"],
            "BOREHOLE_PURPOSE": b["purpose"],
            "BOREHOLE_CODE": b["fdsn_code"],
            "PROJECT": b["project"],
            "TESTBED": b["testbed"],
            "TUNNEL_SECTION": b["tunnel_section"].strip(),
            "LOCATION_TM": b["tunnel_meter"].removeprefix("TM"),
            "BOREHOLE_MOUTH_E": c.get("easting", ""),
            "BOREHOLE_MOUTH_N": c.get("northing", ""),
            "BOREHOLE_MOUTH_H": c.get("elevation", ""),
            "AZIMUTH": c.get("azimuth", ""),
            "BOREHOLE_DIP": c.get("dip", ""),
            "COORDSYS": "global-local" if c else "",
            "BOREHOLE_GEOMETRY": b["geometry"],
            "BOREHOLE_DIAMETER": b["diameter"],
            "BOREHOLE_LENGTH": b["length"],
            "DRILLSTYLE": b["drilling_style"],
            "CORE_DIAMETER": b["core_diameter"],
            "DRILLING_START": b["drilling_start"],
            "DRILLING_PERIOD": b["drilling_end"],
            "BOREHOLE_COMPLETION": b["status"],
            "NOTES": b["remarks"],
        })  # fmt: skip
    return out


def stubs(installs: dict[str, list[list]]) -> dict[str, tuple[str, list[dict]]]:
    seismic = installs["SEIS_SENSOR_INSTAL"]
    sensors = {}
    for row in seismic:
        for parent in row[7].split("\n"):
            if parent.startswith("/EQUIPMENT/SENSOR_CATALOG/"):
                sensors[parent.rsplit("/", 1)[1]] = row[9]["SERIAL_NUMBER"]
    computers = sorted({row[9]["COMPUTER"].rsplit("/", 1)[1] for row in installs["SENSOR_INSTAL"] if row[9]["COMPUTER"]})
    return {
        "SEIS_SENSOR": ("/EQUIPMENT/SENSOR_CATALOG/SEISMIC_SENSORS",
                        [{"code": c, "SERIAL_NUMBER": s, "NOTES": STUB} for c, s in sorted(sensors.items())]),
        "DEVICE": ("/EQUIPMENT/SENSOR_CATALOG/DEVICES",
                   [{"code": c, "NAME": c, "PRODUCT.DESCRIPTION": STUB} for c in computers]),
        "SENSORS": ("/EQUIPMENT/SENSOR_CATALOG/TILTMETERS",
                    [{"code": "LY1066", "SERIAL_NUMBER": "LY1066", "SENSOR_TYPE": "A: Tilt Meter",
                      "NOTES": "not in inventory export"}]),
    }  # fmt: skip


def section(ws, sample_type: str, props: list[str], rows: list[list]) -> None:
    ws.append(["SAMPLE"])
    ws.append(["Sample type"])
    ws.append([sample_type])
    ws.append(ATTRIBUTES + props)
    for row in rows:
        ws.append(row[:9] + [row[9].get(p, "") for p in props])
    ws.append([])


def build(lab: Path, csv_dir: Path) -> Workbook:
    codes = assignment_codes(lab / "all-object-types.2026-09-23" / "object-types.xlsx")
    exported = {}
    for name in OBJECT_EXPORTS:
        sample_type, rows = from_export(lab / name, codes)
        exported.setdefault(sample_type, []).extend(rows)

    holes = boreholes(csv_dir / "borehole_information.csv", csv_dir / "borehole_mouth_coord.csv")
    bad = [h["code"] for h in holes if not re.fullmatch(r"[A-Za-z0-9_.-]+", h["code"])]
    if bad:
        raise SystemExit(f"borehole names that are not valid codes: {bad}")
    new = {"BOREHOLES": objects("/INFRASTRUCTURE/BOREHOLES/BOREHOLES", holes)}
    for sample_type, (collection, rows) in stubs(exported).items():
        new[sample_type] = objects(collection, rows)

    out = Workbook()
    ws = out.active
    ws.append(["SPACE"])
    ws.append(["Code", "Description"])
    for code, description in SPACES.items():
        ws.append([code, description])
    ws.append([])
    ws.append(["PROJECT"])
    ws.append(["Identifier", "Code", "Space"])
    for p in PROJECTS:
        ws.append([p, p.rsplit("/", 1)[1], p.split("/")[1]])
    ws.append([])
    ws.append(["EXPERIMENT"])
    ws.append(["Experiment type"])
    ws.append(["COLLECTION"])
    ws.append(["Identifier", "Code", "Project", "NAME"])
    for c, name in COLLECTIONS.items():
        ws.append([c, c.rsplit("/", 1)[1], c.rsplit("/", 1)[0], name])
    ws.append([])
    for sample_type in wb.BEDRETTO_TYPES:
        rows = new.get(sample_type, []) + exported.get(sample_type, [])
        if rows:
            section(ws, sample_type, codes[sample_type], rows)
            print(f"{sample_type}: {len(rows)}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Write an object-import workbook that seeds the local openBIS")
    ap.add_argument("--lab", type=Path, default=LAB, help="folder of the lab's openBIS exports")
    ap.add_argument("--csv", type=Path, default=CSV, help="folder of the borehole CSVs")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--import", dest="do_import", action="store_true", help="import it into the local openBIS")
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    build(args.lab, args.csv).save(args.out)
    print(args.out)
    if args.do_import:
        Openbis().import_excel(args.out)
        print("imported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
