import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import config  # noqa: E402
import openbis_workbook as wb  # noqa: E402
from openbis_api import Openbis  # noqa: E402

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

SPACES = {
    "INFRASTRUCTURE": "Boreholes and logging",
    "09_FEAR": "FEAR experiments",
    "EQUIPMENT": "Sensors and devices",
}
PROJECTS = [
    "/INFRASTRUCTURE/BOREHOLES",
    "/09_FEAR/06_FEAR2",
    "/EQUIPMENT/SENSOR_CATALOG",
]
# the lab's borehole collection is unknown (see architecture/collaborator-requests.md); BOREHOLES stands in for it
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


def objects(collection: str, rows: list[dict]) -> list[dict]:
    # new objects in a collection; each row has a code and properties by code
    project = collection.rsplit("/", 1)[0]
    return [
        {
            "identifier": f"{project}/{r.pop('code')}",
            "collection": collection,
            "properties": r,
        }
        for r in rows
    ]


def boreholes(path: Path, coords: Path) -> list[dict]:
    coord = {
        c["coord_id"]: c for c in csv.DictReader(coords.open(encoding="utf-8-sig"))
    }
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


def stubs(exported: list[dict]) -> dict[str, tuple[str, list[dict]]]:
    sensors = {}
    for o in exported:
        if o["type"] == "SEIS_SENSOR_INSTAL":
            for parent in o["parents"]:
                if parent.startswith("/EQUIPMENT/SENSOR_CATALOG/"):
                    sensors[parent.rsplit("/", 1)[1]] = o["properties"]["SERIAL_NUMBER"]
    computers = sorted(
        {
            o["properties"]["COMPUTER"].rsplit("/", 1)[1]
            for o in exported
            if o["type"] == "SENSOR_INSTAL" and o["properties"].get("COMPUTER")
        }
    )
    return {
        # the installations name the model GS100-600, Geospace's GS-100 geophone
        "SEIS_SENSOR": ("/EQUIPMENT/SENSOR_CATALOG/SEISMIC_SENSORS",
                        [{"code": c, "SERIAL_NUMBER": s, "SENSOR_CAT": "P: Geophone", "NOTES": STUB}
                         for c, s in sorted(sensors.items())]),
        "DEVICE": ("/EQUIPMENT/SENSOR_CATALOG/DEVICES",
                   [{"code": c, "NAME": c, "PRODUCT.DESCRIPTION": STUB} for c in computers]),
        "SENSORS": ("/EQUIPMENT/SENSOR_CATALOG/TILTMETERS",
                    [{"code": "LY1066", "SERIAL_NUMBER": "LY1066", "SENSOR_TYPE": "A: Tilt Meter",
                      "NOTES": "not in inventory export"}]),
    }  # fmt: skip


def build(lab: Path, csv_dir: Path) -> list[wb.Section]:
    masterdata = wb.read(lab / "all-object-types.2026-09-23" / "object-types.xlsx")
    codes = wb.assignment_codes(masterdata)
    exported = []
    for name in OBJECT_EXPORTS:
        for o in wb.read_objects(lab / name, masterdata):
            o["parents"] = [p for p in o["parents"] if p not in DROP_PARENTS]
            o["properties"] = {k: v for k, v in o["properties"].items() if k not in BLANK}
            exported.append(o)

    holes = boreholes(
        csv_dir / "borehole_information.csv", csv_dir / "borehole_mouth_coord.csv"
    )
    bad = [h["code"] for h in holes if not re.fullmatch(r"[A-Za-z0-9_.-]+", h["code"])]
    if bad:
        raise SystemExit(f"borehole names that are not valid codes: {bad}")
    new = {"BOREHOLES": objects("/INFRASTRUCTURE/BOREHOLES/BOREHOLES", holes)}
    for sample_type, (collection, rows) in stubs(exported).items():
        new[sample_type] = objects(collection, rows)

    sections = [
        wb.spaces(SPACES),
        wb.projects(PROJECTS),
        wb.collections(COLLECTIONS),
    ]
    for sample_type in config.BEDRETTO_TYPES:
        rows = new.get(sample_type, []) + [o for o in exported if o["type"] == sample_type]
        if rows:
            sections.append(wb.samples(sample_type, rows, codes[sample_type]))
            print(f"{sample_type}: {len(rows)}")
    return sections


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Write an object-import workbook that seeds the local openBIS"
    )
    ap.add_argument(
        "--lab", type=Path, default=LAB, help="folder of the lab's openBIS exports"
    )
    ap.add_argument("--csv", type=Path, default=CSV, help="folder of the borehole CSVs")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help="import it into the local openBIS",
    )
    args = ap.parse_args()

    wb.write(build(args.lab, args.csv), args.out)
    print(args.out)
    if args.do_import:
        Openbis().import_excel(args.out)
        print("imported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
