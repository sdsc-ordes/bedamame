import csv
from pathlib import Path

import pytest
from rdflib import RDF, RDFS, Graph, URIRef
from rdflib.namespace import SH, SKOS

import annotate_masterdata as am
import config
import openbis_workbook as wb
import validate as v

ROOT = Path(__file__).resolve().parent.parent
# a fresh master-data export of the 12 types from the local openBIS 7.0, before annotation
MASTERDATA = ROOT / "tests" / "fixtures" / "openbis-masterdata.xlsx"
MAPPING = ROOT / "mapping"
# standard vocabularies whose terms are used as they are
EXTERNAL = {"schema", "rdfs", "sosa", "ssn"}


def rows(name: str) -> list[dict]:
    with (MAPPING / name).open() as f:
        return list(csv.DictReader(f))


def iri(curie: str) -> URIRef:
    return URIRef(config.expand(curie))


@pytest.fixture(scope="module")
def masterdata() -> list[wb.Section]:
    return wb.read(MASTERDATA)


@pytest.fixture(scope="module")
def annotations() -> list[dict]:
    return rows("openbis-annotations.csv")


@pytest.fixture(scope="module")
def ontology() -> Graph:
    return Graph().parse(v.ONTOLOGY, format="turtle")


@pytest.fixture(scope="module")
def vocab() -> Graph:
    return Graph().parse(v.VOCAB, format="turtle")


@pytest.fixture(scope="module")
def shapes() -> Graph:
    return Graph().parse(v.SHAPES, format="turtle")


def bedretto_types(sections: list[wb.Section]) -> list[wb.Section]:
    return [
        s
        for s in sections
        if s.kind == "SAMPLE_TYPE" and s.code in config.BEDRETTO_TYPES
    ]


def vocabulary_of(sections: list[wb.Section]) -> dict[tuple[str, str], str]:
    return {
        (s.code, s.children.get(r, "Code")): s.children.get(r, "Vocabulary code")
        for s in bedretto_types(sections)
        for r in s.children.rows
        if s.children.get(r, "Vocabulary code")
    }


def test_one_row_per_type_and_assignment(masterdata, annotations):
    keys = [(r["object_type"], r["property_code"]) for r in annotations]
    expected = [
        (s.code, code)
        for s in bedretto_types(masterdata)
        for code in ["", *(s.children.get(r, "Code") for r in s.children.rows)]
    ]
    assert len(keys) == len(set(keys))
    assert sorted(keys) == sorted(expected)


def test_kind_and_match_follow_the_term(annotations):
    for r in annotations:
        prefix = r["term"].split(":")[0]
        assert r["kind"] == ("assignment" if r["property_code"] else "type"), r
        assert r["match"] == (
            "skip" if not r["term"] else "bed" if prefix == "bed" else "standard"
        ), r
        assert r["term"] or (r["kind"] == "assignment" and r["notes"]), r


def test_terms_resolve(annotations, ontology):
    classes = set(ontology.subjects(RDF.type, RDFS.Class))
    properties = set(ontology.subjects(RDF.type, RDF.Property))
    for r in annotations:
        if not r["term"]:
            continue
        prefix = r["term"].split(":")[0]
        assert prefix in config.ANNOTATION_SOURCES, r
        if prefix == "bed":
            assert iri(r["term"]) in (classes if r["kind"] == "type" else properties), r
        else:
            assert prefix in EXTERNAL, r


def test_units_and_schemes_follow_the_shapes(annotations, shapes, vocab):
    quantity = {
        shapes.value(s, SH.path)
        for s in shapes.subjects(SH.node, URIRef(config.SHAPES + "QuantityValueShape"))
    }
    schemes: dict[URIRef, set] = {}
    for s, scheme in shapes.subject_objects(URIRef(config.SHAPES + "inScheme")):
        schemes.setdefault(shapes.value(s, SH.path), set()).add(scheme)
    for r in annotations:
        if r["kind"] != "assignment" or not r["term"]:
            assert not (r["unit"] or r["scheme"]), r
            continue
        term = iri(r["term"])
        assert bool(r["unit"]) == (term in quantity), r
        assert r["unit"] == "" or r["unit"].startswith("unit:"), r
        if term in schemes:
            assert r["scheme"] and iri(r["scheme"]) in schemes[term], r
        else:
            assert r["scheme"] == "", r
        if r["scheme"]:
            assert (iri(r["scheme"]), RDF.type, SKOS.ConceptScheme) in vocab, r


def test_vocabulary_terms_map_into_the_property_scheme(masterdata, annotations, vocab):
    vocabularies = vocabulary_of(masterdata)
    schemes: dict[str, set] = {}
    for r in annotations:
        voc = vocabularies.get((r["object_type"], r["property_code"]))
        if voc and r["scheme"]:
            schemes.setdefault(voc, set()).add(iri(r["scheme"]))
    exported = {
        (s.code, s.children.get(r, "Code"))
        for s in masterdata
        if s.kind == "VOCABULARY_TYPE" and s.code in schemes
        for r in s.children.rows
    }
    terms = rows("openbis-terms.csv")
    assert {(t["vocabulary_code"], t["term_code"]) for t in terms} == exported
    for t in terms:
        concept = iri(t["concept"])
        assert vocab.value(concept, SKOS.inScheme) in schemes[t["vocabulary_code"]], t


def test_collections_name_an_experiment():
    for r in rows("collections.csv"):
        assert r["openbis_path"].startswith("/") and r["experiment"], r


def test_annotating_changes_only_the_ontology_columns(tmp_path):
    types, items = am.annotate(wb.read(MASTERDATA), am.load_mapping())
    wb.write(types, tmp_path / "masterdata.xlsx")
    after = {s.code: s for s in wb.read(tmp_path / "masterdata.xlsx")}
    before = {s.code: s for s in bedretto_types(wb.read(MASTERDATA))}
    assert after.keys() == before.keys()

    def cell(table, row, header):
        return str(table.get(row, header) or "")

    for code, b in before.items():
        a = after[code]
        for tb, ta in ((b.entity, a.entity), (b.children, a.children)):
            assert len(tb.rows) == len(ta.rows)
            for rb, ra in zip(tb.rows, ta.rows):
                for h in set(tb.header) | set(ta.header):
                    if h not in am.COLUMNS:
                        assert cell(tb, rb, h) == cell(ta, ra, h), (code, h)
    added = [i for i in items if i["status"] == "add"]
    assert len(added) == sum(1 for r in rows("openbis-annotations.csv") if r["term"])
