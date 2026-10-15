from pathlib import Path

import pytest
from pyshacl import validate
from rdflib import Graph, URIRef
from rdflib.namespace import SH

import config
import validate as v

ROOT = Path(__file__).resolve().parent.parent
CRATE_SHAPES = ROOT / "ontology" / "crate" / "crate-shapes.ttl"

PREFIXES = config.turtle_prefixes(
    "bed",
    "bedv",
    "bdr",
    "schema",
    "sosa",
    "ssn",
    "prov",
    "qudt",
    "unit",
    "xsd",
    "skos",
    "foaf",
)

VALID = """
bdr:core1 a bed:Core ; schema:name "BFE_A_01 core 1" ;
    bed:ofBorehole bdr:dgqga6alw5gybldbmlxgxymvf4 ;
    bed:topDepth    [ a qudt:QuantityValue ; qudt:numericValue 0 ; qudt:hasUnit unit:M ] ;
    bed:bottomDepth [ a qudt:QuantityValue ; qudt:numericValue 2 ; qudt:hasUnit unit:M ] ;
    bed:coreDiameter [ a qudt:QuantityValue ; qudt:numericValue 96 ; qudt:hasUnit unit:MilliM ] ;
    bed:mass [ a qudt:QuantityValue ; qudt:numericValue 6.44 ; qudt:hasUnit unit:KiloGM ] ;
    bed:chargeNumber "4697" ; bed:storageLocation "B5A3" ; bed:coreBoxNumber 3 ; bed:forRequest bdr:request1 .

bdr:request1 a bed:CoreRequest ; schema:name "core 1 request" ; bed:requestedBy bdr:person1 ;
    bed:purpose "porosity" ; bed:startDate "2025-10-01"^^xsd:date ; bed:endDate "2025-12-01"^^xsd:date ;
    bed:sampleDestroyed false ; bed:returnedToStorage true .

bdr:person1 a prov:Agent, foaf:Person ; schema:name "Josiah Carberry" ;
    schema:identifier "https://orcid.org/0000-0002-1825-0097" ;
    schema:affiliation bdr:org1 ; schema:email "josiah@example.org" .

bdr:org1 a prov:Agent, foaf:Organization ; schema:name "Example Lab" .

bdr:corelog1 a bed:CoreLog ; schema:name "core 1 log" ;
    bed:ofCore bdr:core1 ; bed:rockClass bedv:rock-class-igneous ; bed:rockType "granite" ;
    bed:geologicalUnit "Rotondo granite" .

bdr:plug1 a bed:CoreSample ; schema:name "core 1 plug 1" ;
    sosa:isSampleOf bdr:core1 ; bed:subsampleType bedv:subsample-type-plug ;
    bed:topDepth    [ a qudt:QuantityValue ; qudt:numericValue 1.0 ; qudt:hasUnit unit:M ] ;
    bed:bottomDepth [ a qudt:QuantityValue ; qudt:numericValue 1.1 ; qudt:hasUnit unit:M ] ;
    bed:requestedBy bdr:dv3mpsfsfnftll6asnosnrwjam .

bdr:analysis1 a bed:LabAnalysis ; schema:name "plug 1 porosity" ;
    sosa:hasFeatureOfInterest bdr:plug1 ;
    sosa:observedProperty bedv:rock-property-porosity ;
    sosa:usedProcedure bedv:analysis-method-ultrasonic-test ;
    sosa:resultTime "2025-10-20T10:00:00Z"^^xsd:dateTime .

bdr:log1 a bed:LoggingRun ; schema:name "BFE_A_01 ATV/OTV run" ;
    bed:loggedBorehole bdr:dgqga6alw5gybldbmlxgxymvf4 ;
    bed:tool bedv:logging-tool-atv, bedv:logging-tool-otv ;
    bed:loggingDirection bedv:logging-direction-upward ;
    bed:centralised true ; bed:fileFormat "tdf" ;
    bed:startDate "2021-06-21"^^xsd:date ; bed:operatedBy bdr:person1 ;
    bed:samplingInterval [ a qudt:QuantityValue ; qudt:numericValue 0.002 ; qudt:hasUnit unit:M ] ;
    bed:depthCorrection [ a qudt:QuantityValue ; qudt:numericValue -0.15 ; qudt:hasUnit unit:M ] .

bdr:tunneldepl a ssn:Deployment ; schema:name "tilt01 on tunnel wall" ;
    ssn:deployedSystem bdr:6elykqev4jep5n4gvvqx5sxsne ;
    ssn:deployedOnPlatform bdr:rqefuczecfce7lg3neucpuxfve ;
    bed:environment bedv:environment-tunnel-wall ;
    bed:tunnelSection bedv:tunnel-section-fear-end-niche ; bed:tunnelMeter "FTM120" ;
    bed:deploymentType bedv:deployment-type-permanent ;
    bed:deployedOn "2025-11-25"^^xsd:date ; bed:deployedBy bdr:person1 ;
    bed:sensorAzimuth [ a qudt:QuantityValue ; qudt:numericValue 5 ; qudt:hasUnit unit:DEG ] ;
    bed:cableLabel "8R.F24201.JP" .

bdr:pos1 a bed:SensorPosition ; schema:name "tilt01 position" ;
    bed:ofDeployment bdr:tunneldepl ;
    bed:coordinateSystem <http://www.opengis.net/def/crs/EPSG/0/2056> ;
    bed:easting 2679334.5 ; bed:northing 1151847.4 ; bed:elevation 1489.46 ;
    bed:computedOn "2025-12-01"^^xsd:date ; bed:coordinatesBy bdr:person1 .
"""

# name: (focus node, constraint component it must trip, data)
INVALID = {
    "core top below bottom": ("bdr:bad1", "SPARQLConstraintComponent", """
bdr:bad1 a bed:Core ; schema:name "bad1" ; bed:ofBorehole bdr:dgqga6alw5gybldbmlxgxymvf4 ;
    bed:topDepth    [ a qudt:QuantityValue ; qudt:numericValue 4 ; qudt:hasUnit unit:M ] ;
    bed:bottomDepth [ a qudt:QuantityValue ; qudt:numericValue 2 ; qudt:hasUnit unit:M ] .
"""),
    "core missing borehole": ("bdr:bad2", "MinCountConstraintComponent", """
bdr:bad2 a bed:Core ; schema:name "bad2" ;
    bed:topDepth    [ a qudt:QuantityValue ; qudt:numericValue 0 ; qudt:hasUnit unit:M ] ;
    bed:bottomDepth [ a qudt:QuantityValue ; qudt:numericValue 2 ; qudt:hasUnit unit:M ] .
"""),
    "rock class from wrong scheme": ("bdr:bad3", "InSchemeConstraintComponent", """
bdr:bad3 a bed:CoreLog ; schema:name "bad3" ; bed:ofCore bdr:core1 ; bed:rockClass bedv:coupling-sanded .
"""),
    "sample of a borehole": ("bdr:bad4", "ClassConstraintComponent", """
bdr:bad4 a bed:CoreSample ; schema:name "bad4" ; sosa:isSampleOf bdr:dgqga6alw5gybldbmlxgxymvf4 .
"""),
    "analysis of a borehole": ("bdr:bad5", "OrConstraintComponent", """
bdr:bad5 a bed:LabAnalysis ; schema:name "bad5" ;
    sosa:hasFeatureOfInterest bdr:dgqga6alw5gybldbmlxgxymvf4 ; sosa:observedProperty bedv:rock-property-density .
"""),
    "logging run without tool": ("bdr:bad6", "MinCountConstraintComponent", """
bdr:bad6 a bed:LoggingRun ; schema:name "bad6" ; bed:loggedBorehole bdr:dgqga6alw5gybldbmlxgxymvf4 .
"""),
    "tunnel meter without TM": ("bdr:bad7", "PatternConstraintComponent", """
bdr:bad7 a bed:Borehole ; schema:name "bad7" ; bed:tunnelMeter "2611" .
"""),
    "tunnel section as string": ("bdr:bad8", "InSchemeConstraintComponent", """
bdr:bad8 a bed:Borehole ; schema:name "bad8" ; bed:tunnelSection "FEAR Tunnel" .
"""),
    "sensor kind from wrong scheme": ("bdr:bad9", "InSchemeConstraintComponent", """
bdr:bad9 a sosa:Sensor ; schema:name "bad9" ; schema:serialNumber "X1" ; bed:sensorKind bedv:logging-tool-atv .
"""),
    "deployment status from wrong scheme": ("bdr:bad10", "InSchemeConstraintComponent", """
bdr:bad10 a ssn:Deployment ; schema:name "bad10" ;
    ssn:deployedSystem bdr:6elykqev4jep5n4gvvqx5sxsne ; ssn:deployedOnPlatform bdr:rqefuczecfce7lg3neucpuxfve ;
    bed:environment bedv:environment-borehole ; bed:sensorStatus bedv:borehole-status-open .
"""),
    "tunnel meter with another prefix": ("bdr:bad11", "PatternConstraintComponent", """
bdr:bad11 a bed:Borehole ; schema:name "bad11" ; bed:tunnelMeter "XTM12" .
"""),
    "deployment type from wrong scheme": ("bdr:bad12", "InSchemeConstraintComponent", """
bdr:bad12 a ssn:Deployment ; schema:name "bad12" ;
    ssn:deployedSystem bdr:6elykqev4jep5n4gvvqx5sxsne ; ssn:deployedOnPlatform bdr:rqefuczecfce7lg3neucpuxfve ;
    bed:environment bedv:environment-borehole ; bed:deploymentType bedv:coupling-sanded .
"""),
    "deployment date as text": ("bdr:bad13", "DatatypeConstraintComponent", """
bdr:bad13 a ssn:Deployment ; schema:name "bad13" ;
    ssn:deployedSystem bdr:6elykqev4jep5n4gvvqx5sxsne ; ssn:deployedOnPlatform bdr:rqefuczecfce7lg3neucpuxfve ;
    bed:environment bedv:environment-borehole ; bed:deployedOn "25.11.2025" .
"""),
    "collar survey without date": ("bdr:bad14", "MinCountConstraintComponent", """
bdr:bad14 a bed:CollarSurvey ; schema:name "bad14" ; bed:ofBorehole bdr:dgqga6alw5gybldbmlxgxymvf4 ;
    bed:surveyType bedv:location-type-planned ; bed:coordinateSystem bedv:crs-bedretto-local-v1 ;
    bed:easting 1.0 ; bed:northing 2.0 ; bed:elevation 3.0 ; bed:dipConvention "negative downward" .
"""),
    "malformed ORCID": ("bdr:bad15", "PatternConstraintComponent", """
bdr:bad15 a prov:Agent, foaf:Person ; schema:name "bad15" ; schema:identifier "0000-0002-1825-0097" .
"""),
    "person not an agent": ("bdr:bad16", "ClassConstraintComponent", """
bdr:bad16 a foaf:Person ; schema:name "bad16" .
"""),
    "affiliation to a person": ("bdr:bad17", "ClassConstraintComponent", """
bdr:bad17 a prov:Agent, foaf:Person ; schema:name "bad17" ; schema:affiliation bdr:person1 .
"""),
    "sensor position without deployment": ("bdr:bad18", "MinCountConstraintComponent", """
bdr:bad18 a bed:SensorPosition ; schema:name "bad18" ; bed:easting 1.0 .
"""),
    "two sensors with one serial number": ("bdr:bad19", "SPARQLConstraintComponent", """
bdr:bad19 a sosa:Sensor ; schema:name "bad19" ; schema:serialNumber "LY1123" ;
    bed:sensorKind bedv:sensor-type-tilt-meter .
"""),
}  # fmt: skip

SKOS_INVALID = {
    "broader in another scheme": ("bedv:x1", "SPARQLConstraintComponent", """
bedv:x1 a skos:Concept ; skos:inScheme bedv:coupling ; skos:prefLabel "X1"@en ; skos:broader bedv:rock-class-igneous .
"""),
    "broader cycle": ("bedv:x2", "SPARQLConstraintComponent", """
bedv:x2 a skos:Concept ; skos:inScheme bedv:coupling ; skos:prefLabel "X2"@en ; skos:broader bedv:x3 .
bedv:x3 a skos:Concept ; skos:inScheme bedv:coupling ; skos:prefLabel "X3"@en ; skos:broader bedv:x2 .
"""),
    "label clash in scheme": ("bedv:x4", "SPARQLConstraintComponent", """
bedv:x4 a skos:Concept ; skos:inScheme bedv:coupling ; skos:prefLabel "sanded"@en .
"""),
}  # fmt: skip


def results(data: Graph, shapes: Path) -> tuple[bool, set[tuple[URIRef, str]]]:
    conforms, report, _ = validate(
        data_graph=data,
        shacl_graph=Graph().parse(shapes, format="turtle"),
        advanced=True,
        inference="none",
    )
    found = {
        (
            report.value(r, SH.focusNode),
            str(report.value(r, SH.sourceConstraintComponent)).rsplit("#")[-1],
        )
        for r in report.subjects(SH.focusNode, None)
    }
    return conforms, found


def components(found: set, focus: URIRef) -> list[str]:
    return sorted({c for f, c in found if f == focus})


@pytest.fixture(scope="module")
def store() -> Graph:
    g = v.union_graph(v.load_dataset())
    g.parse(data=PREFIXES + VALID, format="turtle")
    return g


@pytest.fixture(scope="module")
def vocab() -> Graph:
    return Graph().parse(v.VOCAB, format="turtle")


@pytest.mark.parametrize(
    "shapes", [v.SHAPES, v.VOCAB_SHAPES, CRATE_SHAPES], ids=lambda p: p.name
)
def test_shapes_are_valid_shacl(shapes):
    conforms, _, text = validate(
        Graph().parse(shapes, format="turtle"), meta_shacl=True, advanced=True
    )
    assert conforms, text


def test_data_and_valid_fixtures_conform(store):
    conforms, found = results(store, v.SHAPES)
    assert conforms, sorted(found)


@pytest.mark.parametrize("focus, component, ttl", INVALID.values(), ids=INVALID.keys())
def test_shapes_catch(store, focus, component, ttl):
    g = Graph() + store
    g.parse(data=PREFIXES + ttl, format="turtle")
    _, found = results(g, v.SHAPES)
    focus = URIRef(config.expand(focus))
    assert (focus, component) in found, components(found, focus)


@pytest.mark.parametrize(
    "focus, component, ttl", SKOS_INVALID.values(), ids=SKOS_INVALID.keys()
)
def test_skos_shapes_catch(vocab, focus, component, ttl):
    g = Graph() + vocab
    g.parse(data=PREFIXES + ttl, format="turtle")
    _, found = results(g, v.VOCAB_SHAPES)
    focus = URIRef(config.expand(focus))
    assert (focus, component) in found, components(found, focus)
