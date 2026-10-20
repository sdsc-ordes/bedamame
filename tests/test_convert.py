import json
from pathlib import Path

import pytest
from rdflib import Graph, Literal, Namespace, URIRef

import config
import openbis_to_rdf as convert
import queries
import validate as v

ROOT = Path(__file__).resolve().parent.parent
# a V3 dump of the local openBIS after the master-data changes and annotation; people's names replaced
EXPORT = ROOT / "tests" / "fixtures" / "openbis-export.json"

BED = Namespace(config.TERMS)
BEDV = Namespace(config.VOCAB)
SCHEMA = Namespace(config.NAMESPACES["schema"])
SSN = Namespace(config.NAMESPACES["ssn"])
QUDT = Namespace(config.NAMESPACES["qudt"])
UNIT = Namespace(config.NAMESPACES["unit"])


@pytest.fixture(scope="module")
def export() -> dict:
    return json.loads(EXPORT.read_text())


@pytest.fixture(scope="module")
def converted(export):
    return convert.convert(export)


@pytest.fixture(scope="module")
def union(converted) -> Graph:
    ds, _ = converted
    return v.union_graph(ds)


def test_dump_annotations_agree_with_the_mapping(export):
    mapping = config.load_mapping()
    for t, info in export["types"].items():
        want = mapping[(t, "")]["term"]
        assert info["annotations"] == [config.expand(want)], t
        for code, p in info["properties"].items():
            m = mapping[(t, code)]
            assert p["annotations"] == (
                [config.expand(m["term"])] if m["term"] else []
            ), (t, code)


def test_converts_without_problems(converted):
    _, problems = converted
    assert problems == []


def test_conforms(union):
    conforms, text, _ = v.run(union, v.SHAPES)
    assert conforms, text


def test_default_graph_is_empty(converted):
    ds, _ = converted
    assert len(ds.default_graph) == 0


def test_tiltmeter_installation(union):
    (install,) = union.subjects(SCHEMA.name, Literal("BFE_D_31_TILT1_4"))
    sensor = union.value(install, SSN.deployedSystem)
    assert union.value(sensor, SCHEMA.serialNumber) == Literal("LY1123")
    borehole = union.value(install, SSN.deployedOnPlatform)
    assert union.value(borehole, SCHEMA.name) == Literal("BFE_D_31")
    assert union.value(install, BED.coupling) == BEDV["coupling-sanded"]
    depth = union.value(install, BED.measuredDepth)
    assert union.value(depth, QUDT.numericValue).toPython() == 14
    assert union.value(depth, QUDT.hasUnit) == UNIT.M
    assert len(set(union.objects(install, BED.deployedBy))) == 2


def test_hydromechanical_deployments(converted):
    ds, _ = converted
    for name, path in queries.STATIC_GRAPHS.items():
        ds.graph(URIRef(config.GRAPH + name)).parse(path, format="turtle")
    rows = list(ds.query(queries.QUERIES["hydromechanical-deployments"]))
    depths = {str(r["serial"]): r["depth_m"].toPython() for r in rows}
    assert depths == {"LY1123": 14, "LY1127": 20, "LY1066": 19, "LY5020": 18}
