import argparse
import csv
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import Workbook
from rdflib import Graph, URIRef
from rdflib.namespace import SKOS

import annotate_masterdata as am
import config
import openbis_workbook as wb
import validate as v
from openbis_api import Openbis

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out" / "openbis" / "changes"
REVIEW = ROOT / "out" / "openbis" / "review"
EXPORT = ROOT / "out" / "openbis" / "export"
CSV_DIR = ROOT / "drive-files" / "CSV"
TERMS = ROOT / "src" / "mapping" / "openbis-terms.csv"

PEOPLE = "/REGISTERS/PEOPLE/PEOPLE_COLLECTION"
ORGANIZATIONS = "/REGISTERS/ORGANIZATIONS/ORGANIZATIONS_COLLECTION"
TESTBEDS = "/REGISTERS/TESTBEDS/TESTBEDS_COLLECTION"
SURVEYS = "/INFRASTRUCTURE/BOREHOLES/BOREHOLE_MOUTH_SURVEYS"
INSTALLS = ["SENSOR_INSTAL", "SEIS_SENSOR_INSTAL"]
SENSORS = ["SENSORS", "SEIS_SENSOR"]

IMPORT = (
    "In the admin UI: **Tools → Import → All**, choose `{file}`, **Mode: Update if exists**, "
    "**Import**. Make a fresh export first and build the change from it, so that it starts "
    "from what is in openBIS now."
)
KEEP_OLD = (
    "The old fields stay as they are. Once the new ones are checked, hide or remove the old ones "
    "from the types in the admin UI."
)


@dataclass
class Export:
    masterdata: list[wb.Section]
    objects: list[dict]
    scripts: dict[str, str] = field(default_factory=dict)

    def section(self, code: str, kind: str = "SAMPLE_TYPE") -> wb.Section | None:
        return next(
            (s for s in self.masterdata if s.kind == kind and s.code == code), None
        )

    def types_with(self, prop: str) -> list[str]:
        return [
            t
            for t in config.BEDRETTO_TYPES
            if (s := self.section(t)) and prop in wb.assignment_codes([s])[t]
        ]

    def property_row(self, prop: str) -> list:
        # an existing property's definition, to assign it to another type unchanged
        for s in self.masterdata:
            if s.kind == "SAMPLE_TYPE" and s.children:
                for r in s.children.rows:
                    if s.children.get(r, "Code") == prop:
                        return [s.children.get(r, h) or "" for h in wb.PROPERTY_HEADER]
        raise SystemExit(f"property {prop} is not in the master-data export")

    def of_type(self, *types: str) -> list[dict]:
        return [o for o in self.objects if o["type"] in types]

    def term_code(self, vocabulary: str, value: str) -> str | None:
        # exports write vocabulary values as labels, imports accept codes and labels
        s = self.section(vocabulary, "VOCABULARY_TYPE")
        for r in s.children.rows if s and s.children else []:
            if value in (s.children.get(r, "Code"), s.children.get(r, "Label")):
                return s.children.get(r, "Code")
        return None


@dataclass
class Change:
    name: str
    title: str
    sections: list[wb.Section]
    note: list[str]
    review: dict[str, list[list]] = field(default_factory=dict)
    terms: list[dict] = field(default_factory=list)


def norm(text) -> str:
    return " ".join(str(text).split()).casefold()


def code_of(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")


def type_row(export: Export, code: str, properties: list[list]) -> wb.Section:
    # an existing type with properties to add; its own row is copied from the export so nothing
    # else changes, less one TYPE. prefix on the script name (see annotate_masterdata.py)
    s = export.section(code)
    if s is None:
        raise SystemExit(f"type {code} is not in the master-data export")
    entity = wb.Table(list(s.entity.header), [list(s.entity.rows[0])])
    am.unprefix_scripts([wb.Section("SAMPLE_TYPE", entity, None)])
    return wb.Section(
        "SAMPLE_TYPE", entity, wb.Table(list(wb.PROPERTY_HEADER), properties)
    )


def updates(
    sample_type: str, objects: list[tuple[dict, dict]], codes: list[str]
) -> wb.Section:
    # objects that exist already: identifier and collection from the export, new property values
    return wb.samples(
        sample_type,
        [{**o, "parents": [], "properties": values} for o, values in objects],
        codes,
    )


def section_of(export: Export, sample_type: str, prop: str) -> str:
    s = export.section(sample_type)
    for r in s.children.rows:
        if s.children.get(r, "Code") == prop:
            return s.children.get(r, "Section") or "General"
    return "General"


def concepts(vocab: Graph, scheme: str) -> list[URIRef]:
    return sorted(vocab.subjects(SKOS.inScheme, URIRef(config.expand(scheme))))


def concept_code(vocab: Graph, concept: URIRef, scheme: str) -> str:
    # term codes come from concept local names, without the scheme's own name
    prefix = config.expand(scheme) + "-"
    if str(concept).startswith(prefix):
        return code_of(str(concept)[len(prefix) :])
    for alt in vocab.objects(concept, SKOS.altLabel):
        if re.fullmatch(r"[A-Z]+:\w+", str(alt)):
            return code_of(str(alt))
    return code_of(str(concept).rsplit("/", 1)[-1])


def curie(iri: URIRef) -> str:
    for prefix, ns in config.NAMESPACES.items():
        if str(iri).startswith(ns) and prefix in ("bedv", "epsg"):
            return f"{prefix}:{str(iri)[len(ns) :]}"
    return str(iri)


def vocabulary_from_scheme(
    vocab: Graph, scheme: str, code: str, existing: dict[str, str] | None = None
) -> tuple[wb.Section, list[dict]]:
    # the openBIS vocabulary for a SKOS scheme; concepts that already have a term keep it
    existing = existing or {}
    terms, rows = [], []
    for c in concepts(vocab, scheme):
        if curie(c) in existing.values():
            continue
        term = concept_code(vocab, c, scheme)
        label = str(vocab.value(c, SKOS.prefLabel))
        terms.append((term, label, str(vocab.value(c, SKOS.definition) or "")))
        rows.append(
            {
                "vocabulary_code": code,
                "term_code": term,
                "term_label": label,
                "concept": curie(c),
            }
        )
    description = str(vocab.value(URIRef(config.expand(scheme)), SKOS.prefLabel))
    return wb.vocabulary(code, description, terms), rows


def extend_vocabulary(
    export: Export, vocab: Graph, scheme: str, code: str
) -> tuple[wb.Section, list[dict], dict[str, str]]:
    # new terms only; an existing vocabulary keeps its description and term codes. Existing means in
    # the export: openbis-terms.csv may list terms of a change that has not been imported yet.
    old = export.section(code, "VOCABULARY_TYPE")
    in_openbis = (
        {old.children.get(r, "Code") for r in old.children.rows} if old else set()
    )
    existing = {t: c for t, c in mapped_terms(code).items() if t in in_openbis}
    section, rows = vocabulary_from_scheme(vocab, scheme, code, existing)
    if old:
        section.entity.set(
            section.entity.rows[0],
            "Description",
            old.entity.get(old.entity.rows[0], "Description") or "",
        )
    term_of = {c: t for t, c in existing.items()} | {
        r["concept"]: r["term_code"] for r in rows
    }
    return section, rows, term_of


def matcher(vocab: Graph, scheme: str, terms: dict[str, str]):
    # free text to a term code, through the concept's labels and hidden labels
    by_label = {}
    for c in concepts(vocab, scheme):
        for p in (SKOS.prefLabel, SKOS.altLabel, SKOS.hiddenLabel):
            for label in vocab.objects(c, p):
                by_label[norm(label)] = terms.get(curie(c))
    return lambda text: by_label.get(norm(text))


def mapped_terms(vocabulary: str) -> dict[str, str]:
    with TERMS.open() as f:
        return {
            r["term_code"]: r["concept"]
            for r in csv.DictReader(f)
            if r["vocabulary_code"] == vocabulary
        }


def split_names(text: str) -> list[str]:
    parts = re.split(r",|\band\b", text)
    return [" ".join(p.split()) for p in parts if p.strip()]


class Agents:
    # people and organisations by name: those already in openBIS, and new ones
    def __init__(self, export: Export):
        self.known = {}
        for o in export.of_type("PERSON", "ORGANIZATION"):
            if name := o["properties"].get("NAME"):
                self.known[norm(name)] = o["identifier"]
        self.new: dict[str, dict] = {}

    def __call__(self, name: str, organisation: bool = False) -> str:
        key = norm(name)
        if key in self.known:
            return self.known[key]
        if key not in self.new:
            collection = ORGANIZATIONS if organisation else PEOPLE
            codes = {n["identifier"].rsplit("/", 1)[1] for n in self.new.values()}
            code, i = code_of(name), 2
            while code in codes:
                code, i = f"{code_of(name)}_{i}", i + 1
            self.new[key] = {
                "identifier": f"{collection.rsplit('/', 1)[0]}/{code}",
                "collection": collection,
                "properties": {"NAME": name},
                "type": "ORGANIZATION" if organisation else "PERSON",
                "uses": 0,
            }
        self.new[key]["uses"] += 1
        return self.new[key]["identifier"]

    def sections(self) -> list[wb.Section]:
        out = []
        for t in ("PERSON", "ORGANIZATION"):
            objects = [n for n in self.new.values() if n["type"] == t]
            if objects:
                out.append(wb.samples(t, objects, ["NAME"]))
        return out

    def review(self) -> list[list]:
        rows = [["type", "code", "name as written", "used", "given name", "family name",
                 "ORCID or ROR", "email"]]  # fmt: skip
        for n in self.new.values():
            ident = n["identifier"].rsplit("/", 1)[1]
            rows.append([n["type"], ident, n["properties"]["NAME"], n["uses"]])
        return rows


def registers() -> list[wb.Section]:
    return [
        wb.spaces({"REGISTERS": "People, organisations and test beds"}),
        wb.projects(
            ["/REGISTERS/PEOPLE", "/REGISTERS/ORGANIZATIONS", "/REGISTERS/TESTBEDS"]
        ),
    ]


# change 01: free-text people fields become links to PERSON and ORGANIZATION objects
PEOPLE_LINKS = {
    "DEPLOYMENT_USER": (
        "DEPLOYED_BY",
        "Deployed by",
        "People who installed the sensor",
    ),
    "REMOVAL_USER": ("REMOVED_BY", "Removed by", "People who removed the sensor"),
    "OPERATOR": ("OPERATED_BY", "Operated by", "People who operated the tools"),
    "REQUESTER": ("REQUESTED_BY", "Requested by", "People who requested the cores"),
    "OWNER": ("RESPONSIBLE", "Responsible", "People or groups responsible for it"),
}


def people(export: Export, **_) -> Change:
    if not export.section("PERSON"):
        raise SystemExit("openBIS has no PERSON type; it ships with openBIS 7")
    agents = Agents(export)
    sections, links, review = [], {}, [["object", "field", "as written", "linked to"]]
    for old, (new, label, text) in PEOPLE_LINKS.items():
        data_type = "SAMPLE" if new == "RESPONSIBLE" else "SAMPLE:PERSON"
        for t in export.types_with(old):
            row = wb.property_row(new, label, data_type, f"{text}; replaces {old}",
                                  section_of(export, t, old), multivalued=True)  # fmt: skip
            links.setdefault(t, {"rows": [], "values": {}})["rows"].append(row)
            for o in export.of_type(t):
                if text_value := o["properties"].get(old):
                    group = new == "RESPONSIBLE" and re.fullmatch(
                        r"[A-Z0-9_]+", text_value.strip()
                    )
                    names = [text_value.strip()] if group else split_names(text_value)
                    targets = [agents(n, organisation=bool(group)) for n in names]
                    links[t]["values"].setdefault(o["identifier"], (o, {}))[1][new] = (
                        "\n".join(targets)
                    )
                    review.append(
                        [o["identifier"], old, text_value, ", ".join(targets)]
                    )

    sections += registers()
    sections.append(wb.collections({PEOPLE: "People", ORGANIZATIONS: "Organisations"}))
    person = type_row(export, "PERSON", [
        wb.property_row("PERSON.EMAIL", "Email", "VARCHAR", "Email address"),
        wb.property_row("PERSON.AFFILIATION", "Affiliation", "SAMPLE:ORGANIZATION",
                        "Organisations the person belongs to", multivalued=True),
    ])  # fmt: skip
    sections.append(person)
    for t, link in links.items():
        sections.append(type_row(export, t, link["rows"]))
    sections += agents.sections()
    for t, link in links.items():
        codes = [r[0] for r in link["rows"]]
        if link["values"]:
            sections.append(updates(t, list(link["values"].values()), codes))

    counts = {t: len(link["values"]) for t, link in links.items()}
    note = [
        "Adds people and organisations as objects, and links to them in place of the free-text "
        "name fields.",
        "",
        "- PERSON gets Email and Affiliation (a link to ORGANIZATION objects).",
        "- New space REGISTERS with collections "
        f"`{PEOPLE}` and `{ORGANIZATIONS}`. Mark REGISTERS as an Inventory space in the ELN "
        "settings.",
        "- New link fields, each next to the free-text field it replaces: "
        + "; ".join(
            f"{new} on {', '.join(export.types_with(old))}"
            for old, (new, _, _) in PEOPLE_LINKS.items()
            if export.types_with(old)
        )
        + ".",
        f"- {sum(n['type'] == 'PERSON' for n in agents.new.values())} people and "
        f"{sum(n['type'] == 'ORGANIZATION' for n in agents.new.values())} organisations are "
        "created from the names in those fields, split at commas and 'and'; "
        + ", ".join(f"{n} {t} objects" for t, n in counts.items() if n)
        + " get links.",
        "",
        "**Before importing**, check the review sheet `out/openbis/review/01-people.xlsx`: one "
        "row per person or organisation as the names were written, and one per link. Correct "
        "names in the change file, or merge objects in openBIS afterwards. Given and family "
        "names, ORCID and email can be added in openBIS later.",
        "",
        KEEP_OLD,
    ]
    return Change("01-people", "People and organisations", sections, note,
                  review={"people": agents.review(), "links": review})  # fmt: skip


# change 02: the TESTBED vocabulary becomes a register of TESTBED objects
def testbeds(export: Export, **_) -> Change:
    vocabulary = export.section("TESTBED", "VOCABULARY_TYPE")
    if vocabulary is None:
        raise SystemExit("no TESTBED vocabulary in the master-data export")
    beds = [
        {
            "identifier": f"/REGISTERS/TESTBEDS/{vocabulary.children.get(r, 'Code')}",
            "collection": TESTBEDS,
            "properties": {
                "NAME": vocabulary.children.get(r, "Label"),
                "TESTBED.ABBREVIATION": vocabulary.children.get(r, "Code"),
                "TESTBED.DESCRIPTION": vocabulary.children.get(r, "Description") or "",
            },
        }
        for r in vocabulary.children.rows
    ]
    testbed = wb.sample_type("TESTBED", "A test bed of the laboratory", "TB", [
        wb.property_row("NAME", "Name", "VARCHAR", "Name", internal=True),
        wb.property_row("TESTBED.ABBREVIATION", "Abbreviation", "VARCHAR",
                        "Short code of the test bed"),
        wb.property_row("TESTBED.DESCRIPTION", "Description", "VARCHAR",
                        "What the test bed is for"),
    ])  # fmt: skip
    sections = [*registers(), wb.collections({TESTBEDS: "Test beds"}), testbed]
    sections.append(
        wb.samples(
            "TESTBED", beds, ["NAME", "TESTBED.ABBREVIATION", "TESTBED.DESCRIPTION"]
        )
    )
    unmatched, linked = [], 0
    for t in export.types_with("TESTBED"):
        row = wb.property_row("TEST_BED", "Test bed", "SAMPLE:TESTBED",
                              "The test bed it belongs to; replaces TESTBED",
                              section_of(export, t, "TESTBED"))  # fmt: skip
        sections.append(type_row(export, t, [row]))
        values = []
        for o in export.of_type(t):
            if label := o["properties"].get("TESTBED"):
                if code := export.term_code("TESTBED", label):
                    values.append((o, {"TEST_BED": f"/REGISTERS/TESTBEDS/{code}"}))
                else:
                    unmatched.append(f"{o['identifier']}: {label}")
        if values:
            sections.append(updates(t, values, ["TEST_BED"]))
            linked += len(values)
    note = [
        "Turns the TESTBED vocabulary into a register of test beds, so that a test bed can "
        "carry a description and other facts.",
        "",
        f"- New type TESTBED (name, abbreviation, description) and collection `{TESTBEDS}`.",
        f"- {len(beds)} test beds, one per vocabulary term: "
        + ", ".join(b["properties"]["NAME"] for b in beds)
        + ".",
        f"- New field TEST_BED, a link to a test bed, on {', '.join(export.types_with('TESTBED'))}; "
        f"{linked} objects get it from their current TESTBED value.",
    ]
    if unmatched:
        note += [
            "",
            "Values that match no term, left unlinked:",
            *[f"- {u}" for u in unmatched],
        ]
    note += ["", KEEP_OLD + " The TESTBED vocabulary can then go too."]
    return Change("02-testbeds", "Test beds", sections, note)


# change 03: borehole mouth surveys, one object per survey, from borehole_mouth_coord.csv
def coordinate_vocabularies(vocab: Graph) -> tuple[list[wb.Section], list[dict]]:
    survey, a = vocabulary_from_scheme(vocab, "bedv:location-type", "SURVEY_TYPE")
    crs, b = vocabulary_from_scheme(vocab, "bedv:crs", "COORDINATE_SYSTEM")
    return [survey, crs], a + b


def borehole_ids(export: Export) -> dict[str, str]:
    out = {}
    for o in export.of_type("BOREHOLES"):
        out[o["identifier"].rsplit("/", 1)[1]] = o["identifier"]
        if name := o["properties"].get("BOREHOLE_NAME"):
            out[name] = o["identifier"]
    return out


def mouth_surveys(export: Export, csv_dir: Path = CSV_DIR, **_) -> Change:
    vocab = Graph().parse(v.VOCAB, format="turtle")
    vocabularies, terms = coordinate_vocabularies(vocab)
    survey_type = matcher(
        vocab, "bedv:location-type", {r["concept"]: r["term_code"] for r in terms}
    )
    coordinate = [
        r["term_code"] for r in terms if r["concept"] == "bedv:crs-bedretto-local-v1"
    ][0]
    properties = [
        wb.property_row("BOREHOLE", "Borehole", "SAMPLE:BOREHOLES", "The borehole"),
        wb.property_row("SURVEY_TYPE", "Survey type", "CONTROLLEDVOCABULARY",
                        "How the position was obtained", vocabulary="SURVEY_TYPE"),
        wb.property_row("SURVEY_DATE", "Survey date", "DATE", "When it was surveyed or planned"),
        wb.property_row("SURVEY_SOURCE", "Source", "VARCHAR", "Where the values come from"),
        wb.property_row("SURVEYED_BY", "Surveyed by", "SAMPLE",
                        "People or organisations who surveyed or planned it", multivalued=True),
        wb.property_row("COORDINATE_SYSTEM", "Coordinate system", "CONTROLLEDVOCABULARY",
                        "The coordinate system of easting, northing and elevation",
                        vocabulary="COORDINATE_SYSTEM"),
        *[export.property_row(p) for p in ("BOREHOLE_MOUTH_E", "BOREHOLE_MOUTH_N", "BOREHOLE_MOUTH_H")],
        wb.property_row("SURVEY_AZIMUTH", "Azimuth [deg]", "REAL", "Azimuth of the borehole axis at the mouth"),
        wb.property_row("SURVEY_DIP", "Dip [deg]", "REAL", "Dip of the borehole axis at the mouth"),
        wb.property_row("DIP_CONVENTION", "Dip convention", "VARCHAR", "How to read the sign of the dip"),
        export.property_row("NOTES"),
    ]  # fmt: skip
    surveys = wb.sample_type(
        "BOREHOLE_MOUTH_SURVEY",
        "A survey of a borehole mouth: position and orientation, planned or measured",
        "BMS",
        properties,
    )
    boreholes = borehole_ids(export)
    agents = Agents(export)
    objects, unresolved, empty = [], [], []
    with (csv_dir / "borehole_mouth_coord.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r["borehole_name"] not in boreholes:
            unresolved.append(r["borehole_name"])
            continue
        if not all(r[c].strip() for c in ("easting", "northing", "elevation")):
            empty.append(r["borehole_name"])
            continue
        kind = survey_type(r["type"])
        objects.append({
            "identifier": f"/INFRASTRUCTURE/BOREHOLES/{code_of(r['borehole_name'])}_"
                          f"{kind}_{r['date'].replace('-', '')}",
            "collection": SURVEYS,
            "properties": {
                "BOREHOLE": boreholes[r["borehole_name"]], "SURVEY_TYPE": kind,
                "SURVEY_DATE": r["date"], "SURVEY_SOURCE": r["source"],
                "SURVEYED_BY": agents(r["provided_by"]) if r["provided_by"] else "",
                "COORDINATE_SYSTEM": coordinate, "BOREHOLE_MOUTH_E": r["easting"],
                "BOREHOLE_MOUTH_N": r["northing"], "BOREHOLE_MOUTH_H": r["elevation"],
                "SURVEY_AZIMUTH": r["azimuth"], "SURVEY_DIP": r["dip"],
                "DIP_CONVENTION": r["dip_convention"],
            },
        })  # fmt: skip
    codes = [p[0] for p in properties]
    sections = [*vocabularies, surveys, *registers()]
    sections.append(
        wb.collections({SURVEYS: "Borehole mouth surveys", PEOPLE: "People"})
    )
    sections += agents.sections()
    sections.append(wb.samples("BOREHOLE_MOUTH_SURVEY", objects, codes))

    differences = compare_positions(export, objects)
    note = [
        "Records borehole mouth positions as surveys: one object per planned, staked-out or "
        "as-built position, with its date, source and surveyor, so that the history is kept.",
        "",
        f"- New type BOREHOLE_MOUTH_SURVEY and collection `{SURVEYS}`.",
        "- New vocabularies SURVEY_TYPE and COORDINATE_SYSTEM, made from the Bedretto vocabulary.",
        f"- {len(objects)} surveys from `borehole_mouth_coord.csv`, in the laboratory's local grid "
        "(the file names no coordinate system).",
        f"- {sum(n['type'] == 'PERSON' for n in agents.new.values())} people created for "
        "'provided by'; see `out/openbis/review/03-borehole-mouth-surveys.xlsx`.",
    ]
    if unresolved:
        note += [
            "",
            "Rows whose borehole is not in openBIS, left out: "
            + ", ".join(unresolved)
            + ".",
        ]
    if empty:
        note += [
            "",
            "Rows without easting, northing or elevation, left out: "
            + ", ".join(empty)
            + ".",
        ]
    note += ["", "## Compared with the position fields on BOREHOLES", ""]
    if differences:
        note += [
            "| Borehole | Field | On the borehole | Latest survey |",
            "|---|---|---|---|",
        ]
        note += [f"| {b} | {f} | {x} | {y} |" for b, f, x, y in differences]
    else:
        note.append("Every borehole's position fields match its latest survey.")
    note += [
        "",
        "The position fields on BOREHOLES stay for now; retire them once the surveys are checked.",
    ]
    return Change("03-borehole-mouth-surveys", "Borehole mouth surveys", sections, note,
                  review={"people": agents.review()}, terms=terms)  # fmt: skip


def compare_positions(export: Export, surveys: list[dict]) -> list[tuple]:
    latest = {}
    for s in sorted(surveys, key=lambda s: s["properties"]["SURVEY_DATE"]):
        latest[s["properties"]["BOREHOLE"]] = s["properties"]
    fields = {"BOREHOLE_MOUTH_E": "BOREHOLE_MOUTH_E", "BOREHOLE_MOUTH_N": "BOREHOLE_MOUTH_N",
              "BOREHOLE_MOUTH_H": "BOREHOLE_MOUTH_H", "AZIMUTH": "SURVEY_AZIMUTH",
              "BOREHOLE_DIP": "SURVEY_DIP"}  # fmt: skip
    out = []
    for o in export.of_type("BOREHOLES"):
        survey = latest.get(o["identifier"])
        for old, new in fields.items():
            have, want = o["properties"].get(old), survey and survey.get(new)
            if have is None and not want:
                continue
            try:
                same = (
                    have is not None and want and abs(float(have) - float(want)) < 1e-6
                )
            except ValueError:
                same = False
            if not same:
                name = o["identifier"].rsplit("/", 1)[1]
                out.append((name, old, have or "", want or "no survey"))
    return out


# change 04: sensor positions, one object per computed position of an installation
POSITION_FIELDS = ["EASTING", "NORTHING", "ELEVATION", "LAT", "LONG", "COORD_DATE"]


def sensor_positions(export: Export, **_) -> Change:
    properties = [
        wb.property_row("INSTALLATION", "Installation", "SAMPLE", "The sensor installation"),
        *[export.property_row(p) for p in POSITION_FIELDS],
        wb.property_row("COORDINATE_SYSTEM", "Coordinate system", "CONTROLLEDVOCABULARY",
                        "The coordinate system of easting, northing and elevation",
                        vocabulary="COORDINATE_SYSTEM"),
        wb.property_row("COORDINATES_BY", "Coordinates computed by", "SAMPLE:PERSON",
                        "People who computed the position", multivalued=True),
        export.property_row("NOTES"),
    ]  # fmt: skip
    positions = wb.sample_type(
        "SENSOR_POSITION",
        "A computed position of an installed sensor",
        "SPOS",
        properties,
    )
    vocab = Graph().parse(v.VOCAB, format="turtle")
    crs = matcher(
        vocab, "bedv:crs", {c: t for t, c in mapped_terms("COORDINATE_SYSTEM").items()}
    )
    agents = Agents(export)
    objects, review = [], [["installation", "field", "as written", "why"]]
    for o in export.of_type(*INSTALLS):
        values = {
            p: o["properties"][p] for p in POSITION_FIELDS if o["properties"].get(p)
        }
        if not values.keys() - {"COORD_DATE"}:
            continue
        if text := o["properties"].get("COORDSYS"):
            values["COORDINATE_SYSTEM"] = crs(text) or ""
            if not values["COORDINATE_SYSTEM"]:
                review.append([o["identifier"], "COORDSYS", text, "no matching term"])
        if who := o["properties"].get("COORD_USER"):
            values["COORDINATES_BY"] = "\n".join(agents(n) for n in split_names(who))
        values["INSTALLATION"] = o["identifier"]
        objects.append({"identifier": f"{o['identifier']}_POSITION",
                        "collection": o["collection"], "properties": values})  # fmt: skip
    sections = [positions]
    if agents.new:
        sections += [
            *registers(),
            wb.collections({PEOPLE: "People"}),
            *agents.sections(),
        ]
    if objects:
        sections.append(
            wb.samples("SENSOR_POSITION", objects, [p[0] for p in properties])
        )
    note = [
        "Adds sensor positions as objects of their own, linked to the installation, so that a "
        "sensor can get a new position without losing the old one.",
        "",
        "- New type SENSOR_POSITION: installation, easting, northing, elevation, latitude, "
        "longitude, coordinate system, computation date, computed by (people), notes.",
        f"- {len(objects)} positions copied from installations that have coordinates.",
    ]
    if agents.new:
        note.append(
            f"- {len(agents.new)} people created from 'Coordinates by'; see "
            "`out/openbis/review/04-sensor-positions.xlsx`."
        )
    if len(review) > 1:
        note.append(
            f"- {len(review) - 1} coordinate systems match no term and stay empty; they are "
            "in the review sheet."
        )
    note += ["", KEEP_OLD]
    return Change("04-sensor-positions", "Sensor positions", sections, note,
                  review={"people": agents.review(), "values": review})  # fmt: skip


# change 05: links to boreholes and sensors in place of names and serial numbers
def object_links(export: Export, **_) -> Change:
    boreholes = borehole_ids(export)
    sensors = {}
    for o in export.of_type(*SENSORS):
        if serial := o["properties"].get("SERIAL_NUMBER"):
            sensors[serial.strip()] = o["identifier"]
    sensor_ids = set(sensors.values())
    borehole = export.property_row("BOREHOLE")
    sections, unresolved, counts = [], [], {}
    # the types that name their borehole as text, and the field they use
    named = {t: "CORES.BOREHOLE" for t in export.types_with("CORES.BOREHOLE")}
    named |= {t: "BOREHOLE_NAME" for t in export.types_with("BOREHOLE_NAME")}
    for t in config.BEDRETTO_TYPES:
        if t == "BOREHOLES" or t not in named:
            continue
        rows = [list(borehole)]
        rows[0][wb.PROPERTY_HEADER.index("Section")] = section_of(export, t, named[t])
        codes = ["BOREHOLE"]
        if t in INSTALLS:
            rows.append(wb.property_row("SENSOR", "Sensor", "SAMPLE", "The installed sensor",
                                        section_of(export, t, "SERIAL_NUMBER")))  # fmt: skip
            codes.append("SENSOR")
        sections.append(type_row(export, t, rows))
        values = []
        for o in export.of_type(t):
            p, found = o["properties"], {}
            name = p.get("BOREHOLE_NAME") or p.get("CORES.BOREHOLE")
            parents = o["parents"]
            via_parent = [x for x in parents if x in boreholes.values()]
            if via_parent or (name and name.strip() in boreholes):
                found["BOREHOLE"] = (
                    via_parent[0] if via_parent else boreholes[name.strip()]
                )
            elif name:
                unresolved.append(f"{o['identifier']}: borehole {name}")
            if "SENSOR" in codes:
                serial = (p.get("SERIAL_NUMBER") or "").strip()
                via_parent = [x for x in parents if x in sensor_ids]
                if via_parent or serial in sensors:
                    found["SENSOR"] = via_parent[0] if via_parent else sensors[serial]
                elif serial:
                    unresolved.append(
                        f"{o['identifier']}: sensor with serial number {serial}"
                    )
            if found:
                values.append((o, found))
        if values:
            sections.append(updates(t, values, codes))
            counts[t] = len(values)
    note = [
        "Links installations, logging runs and cores to their borehole, and installations to "
        "their sensor, in place of names and serial numbers typed as text.",
        "",
        "- New field BOREHOLE (a link to a borehole) on "
        + ", ".join(s.code for s in sections if s.kind == "SAMPLE_TYPE")
        + "; SENSOR (a link to a sensor) on the installation types.",
        "- Links come from the parents where the object has them, otherwise from the borehole "
        "name and the serial number.",
        "- " + ", ".join(f"{n} {t}" for t, n in counts.items()) + " objects get links.",
    ]
    if unresolved:
        note += ["", "Not found, left unlinked:", *[f"- {u}" for u in unresolved]]
    note += [
        "",
        KEEP_OLD
        + " The parents can be removed from the seismic installations as well; nothing "
        "reads them any more.",
    ]
    return Change("05-object-links", "Links to boreholes and sensors", sections, note)


# change 06: free text and yes/no fields become vocabularies made from the Bedretto vocabulary
CONVERSIONS = [
    # old field, new field, vocabulary, scheme, several values
    ("TUNNEL_SECTION", "TUNNEL_SECTION_TERM", "TUNNEL_SECTION", "bedv:tunnel-section", False),
    ("BOREHOLE_GEOMETRY", "BOREHOLE_GEOMETRY_TERM", "BOREHOLE_GEOMETRY", "bedv:borehole-geometry", False),
    ("DRILLSTYLE", "DRILLSTYLE_TERM", "DRILLING_STYLE", "bedv:drilling-style", False),
    ("DRILL_METHOD", "DRILL_METHOD_TERM", "DRILLING_STYLE", "bedv:drilling-style", False),
    ("BOREHOLE_COMPLETION", "BOREHOLE_COMPLETION_TERM", "BOREHOLE_STATUS", "bedv:borehole-status", False),
    ("ROCK_CLASSIFICATION", "ROCK_CLASSIFICATION_TERM", "ROCK_CLASS", "bedv:rock-class", False),
    ("TOOL", "TOOL_TERM", "LOGGING_TOOL", "bedv:logging-tool", True),
    ("DEPLOYMENT_TYPE", "DEPLOYMENT_TYPE_TERM", "DEPLOYMENT_TYPE", "bedv:deployment-type", False),
]  # fmt: skip
ENVIRONMENT = {
    "SENSOR_BOREHOLE": "bedv:environment-borehole",
    "SENSOR_WALL": "bedv:environment-tunnel-wall",
    "SENSOR_TUNNEL": "bedv:environment-tunnel-surface",
    "SENSOR_TRENCH": "bedv:environment-tunnel-trench",
    "SENSOR_SURFACE": "bedv:environment-on-the-surface",
}


def vocabularies(export: Export, **_) -> Change:
    vocab = Graph().parse(v.VOCAB, format="turtle")
    sections, all_terms, review = [], [], [["object", "field", "value", "why"]]
    term_of: dict[str, dict[str, str]] = {}
    schemes = {(voc, scheme) for _, _, voc, scheme, _ in CONVERSIONS}
    schemes.add(("INSTALLATION_ENVIRONMENT", "bedv:environment"))
    for voc, scheme in sorted(schemes):
        section, terms, term_of[voc] = extend_vocabulary(export, vocab, scheme, voc)
        if section.children.rows:
            sections.append(section)
        all_terms += terms

    rows: dict[str, list] = {}
    values: dict[str, dict] = {}
    converted = []
    for old, new, voc, scheme, several in CONVERSIONS:
        match = matcher(vocab, scheme, term_of[voc])
        for t in export.types_with(old):
            label = export.property_row(old)[wb.PROPERTY_HEADER.index("Property label")]
            rows.setdefault(t, []).append(
                wb.property_row(new, label, "CONTROLLEDVOCABULARY", f"{label}; replaces {old}",
                                section_of(export, t, old), vocabulary=voc, multivalued=several)
            )  # fmt: skip
            converted.append(f"{old} on {t} → {new}")
            for o in export.of_type(t):
                if not (text := o["properties"].get(old)):
                    continue
                parts = text.split(",") if several else [text]
                codes = [match(p) for p in parts if p.strip()]
                if all(codes):
                    entry = values.setdefault(t, {}).setdefault(
                        o["identifier"], (o, {})
                    )
                    # several vocabulary terms are comma-separated; several links newline-separated
                    entry[1][new] = ", ".join(codes)
                else:
                    review.append([o["identifier"], old, text, "no matching term"])
    for t in INSTALLS:
        if not export.section(t):
            continue
        rows.setdefault(t, []).append(wb.property_row(
            "INSTALLATION_ENVIRONMENT", "Installation environment", "CONTROLLEDVOCABULARY",
            "Where the sensor is installed; replaces the yes/no installation fields",
            section_of(export, t, "SENSOR_BOREHOLE"), vocabulary="INSTALLATION_ENVIRONMENT",
        ))  # fmt: skip
        for o in export.of_type(t):
            chosen = [f for f in ENVIRONMENT if o["properties"].get(f) == "true"]
            if len(chosen) == 1:
                code = term_of["INSTALLATION_ENVIRONMENT"][ENVIRONMENT[chosen[0]]]
                entry = values.setdefault(t, {}).setdefault(o["identifier"], (o, {}))
                entry[1]["INSTALLATION_ENVIRONMENT"] = code
            elif chosen:
                review.append(
                    [o["identifier"], ", ".join(chosen), "true", "more than one"]
                )
    for t, assignments in rows.items():
        sections.append(type_row(export, t, assignments))
    for t, objects in values.items():
        codes = [r[0] for r in rows[t]]
        sections.append(updates(t, list(objects.values()), codes))
    note = [
        "Turns free-text fields with a fixed set of values, and the yes/no installation fields, "
        "into fields with a vocabulary, so that values are spelt one way and can be searched.",
        "",
        "- New vocabularies from the Bedretto vocabulary: "
        + ", ".join(s.code for s in sections if s.kind == "VOCABULARY_TYPE")
        + ". Existing terms keep their codes.",
        "- New fields: " + "; ".join(converted) + "; INSTALLATION_ENVIRONMENT on the "
        "installation types, from Borehole, Wall, Tunnel Surface, Trench and Surface "
        "Installation.",
        f"- {sum(len(o) for o in values.values())} objects get values, matched by label, "
        "ignoring case and extra spaces.",
        f"- {len(review) - 1} values match no term or need a choice; they are in "
        "`out/openbis/review/06-vocabularies.xlsx` and stay empty.",
        "",
        KEEP_OLD,
    ]
    return Change("06-vocabularies", "Vocabularies", sections, note,
                  review={"values": review}, terms=all_terms)  # fmt: skip


CHANGES = {
    "01": people,
    "02": testbeds,
    "03": mouth_surveys,
    "04": sensor_positions,
    "05": object_links,
    "06": vocabularies,
}


def annotate(change: Change, export: Export) -> None:
    mapping = config.load_mapping()
    for s in change.sections:
        if s.kind != "SAMPLE_TYPE":
            continue
        targets = [(s.children, r, s.children.get(r, "Code")) for r in s.children.rows]
        if export.section(s.code) is None:
            targets.append((s.entity, s.entity.rows[0], ""))
        for table, row, code in targets:
            m = mapping.get((s.code, code))
            if m and m["term"]:
                for column, value in zip(am.COLUMNS, am.annotation(m["term"])):
                    table.set(row, column, value)


def referenced_scripts(change: Change, export: Export) -> dict[str, str]:
    # a type row copied from the export names its validation script; the zip has to carry it
    scripts = {}
    for s in change.sections:
        if s.kind == "SAMPLE_TYPE":
            name = s.entity.get(s.entity.rows[0], "Validation script")
            if name and name not in scripts:
                scripts[name] = (
                    export.scripts.get(f"{s.code}.{name}") or export.scripts[name]
                )
    return scripts


def write(change: Change, export: Export, out: Path, review: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    sheet = out / f"{change.name}.xlsx"
    wb.write(change.sections, sheet)
    target = sheet
    if scripts := referenced_scripts(change, export):
        target = out / f"{change.name}.zip"
        with zipfile.ZipFile(target, "w") as z:
            z.write(sheet, sheet.name)
            for name, text in scripts.items():
                z.writestr(f"scripts/{name}", text)
    if change.review:
        review.mkdir(parents=True, exist_ok=True)
        book = Workbook()
        book.remove(book.active)
        for title, rows in change.review.items():
            ws = book.create_sheet(title[:31])
            for r in rows:
                ws.append(r)
        book.save(review / f"{change.name}.xlsx")
    head = [f"# {change.name}: {change.title}", ""]
    tail = ["", "## Importing", "", IMPORT.format(file=target.name), ""]
    (out / f"{change.name}.md").write_text("\n".join(head + change.note + tail))
    if change.terms:
        with TERMS.open() as f:
            known = {(r["vocabulary_code"], r["term_code"]) for r in csv.DictReader(f)}
        new = [
            t
            for t in change.terms
            if (t["vocabulary_code"], t["term_code"]) not in known
        ]
        if new:
            with TERMS.open("a", newline="") as f:
                csv.DictWriter(
                    f, fieldnames=list(new[0]), lineterminator="\n"
                ).writerows(new)
    return target


def load(masterdata: Path, objects: Path) -> Export:
    sections = wb.read(masterdata)
    scripts = masterdata.parent / "scripts"
    return Export(
        sections,
        wb.read_objects(objects, sections) if objects.exists() else [],
        {f.name: f.read_text() for f in scripts.glob("*.py")},
    )


def export_local(o: Openbis, folder: Path) -> Export:
    if folder.exists():
        shutil.rmtree(folder)
    masterdata = o.export_masterdata(config.ANNOTATED_TYPES, folder)
    objects = o.export_objects(config.ANNOTATED_TYPES, folder / "objects.xlsx")
    return load(masterdata, objects)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the openBIS master-data changes")
    ap.add_argument(
        "changes", nargs="*", default=list(CHANGES), help="change numbers, e.g. 01 02"
    )
    ap.add_argument(
        "--masterdata", type=Path, help="object-types.xlsx of a fresh export"
    )
    ap.add_argument(
        "--objects", type=Path, help="import-compatible export of the objects"
    )
    ap.add_argument(
        "--csv", type=Path, default=CSV_DIR, help="folder of borehole_mouth_coord.csv"
    )
    ap.add_argument("--annotate", action="store_true", help="fill the ontology columns")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--local", action="store_true",
                    help="for each change: export the local openBIS, generate, import")  # fmt: skip
    args = ap.parse_args()

    o = Openbis() if args.local else None
    if o:
        o.require_local()
    elif not args.masterdata:
        ap.error("give --masterdata (and --objects), or --local")
    for number in args.changes:
        export = (
            export_local(o, EXPORT / number)
            if o
            else load(args.masterdata, args.objects or Path("-"))
        )
        change = CHANGES[number](export, csv_dir=args.csv)
        if args.annotate:
            annotate(change, export)
        target = write(change, export, args.out, REVIEW)
        print(target)
        if o:
            o.import_excel(target)
            print("imported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
