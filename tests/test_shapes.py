import sys
from pathlib import Path

from pyshacl import validate
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import SH

ROOT = Path(sys.argv[1])
sys.path.insert(0, str(ROOT / "scripts"))
import validate as v  # noqa: E402

PREFIXES = """
@prefix bed:    <https://example.org/bedretto/terms#> .
@prefix bedv:   <https://example.org/bedretto/vocab/> .
@prefix bdr:    <https://example.org/bedretto/id/> .
@prefix schema: <https://schema.org/> .
@prefix sosa:   <http://www.w3.org/ns/sosa/> .
@prefix ssn:    <http://www.w3.org/ns/ssn/> .
@prefix prov:   <http://www.w3.org/ns/prov#> .
@prefix qudt:   <http://qudt.org/schema/qudt/> .
@prefix unit:   <http://qudt.org/vocab/unit/> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .
@prefix skos:   <http://www.w3.org/2004/02/skos/core#> .
"""

VALID = """
bdr:core1 a bed:Core ; schema:name "BFE_A_01 core 1" ;
    bed:ofBorehole bdr:dgqga6alw5gybldbmlxgxymvf4 ;
    bed:topDepth    [ a qudt:QuantityValue ; qudt:numericValue 0 ; qudt:hasUnit unit:M ] ;
    bed:bottomDepth [ a qudt:QuantityValue ; qudt:numericValue 2 ; qudt:hasUnit unit:M ] ;
    bed:coreDiameter [ a qudt:QuantityValue ; qudt:numericValue 96 ; qudt:hasUnit unit:MilliM ] ;
    bed:mass [ a qudt:QuantityValue ; qudt:numericValue 6.44 ; qudt:hasUnit unit:KiloGM ] ;
    bed:chargeNumber "4697" ; bed:storageLocation "B5A3" .

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
    bed:centralised true ;
    bed:samplingInterval [ a qudt:QuantityValue ; qudt:numericValue 0.002 ; qudt:hasUnit unit:M ] .

bdr:tunneldepl a ssn:Deployment ; schema:name "tilt01 on tunnel wall" ;
    ssn:deployedSystem bdr:6elykqev4jep5n4gvvqx5sxsne ;
    ssn:deployedOnPlatform bdr:rqefuczecfce7lg3neucpuxfve ;
    bed:environment bedv:environment-tunnel-wall ;
    bed:tunnelSection bedv:tunnel-section-main-lab ; bed:tunnelMeter "TM2555" .
"""

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
bdr:bad9 a sosa:Sensor ; schema:name "bad9" ; bed:serialNumber "X1" ; bed:sensorKind bedv:logging-tool-atv .
"""),
    "deployment status from wrong scheme": ("bdr:bad10", "InSchemeConstraintComponent", """
bdr:bad10 a ssn:Deployment ; schema:name "bad10" ;
    ssn:deployedSystem bdr:6elykqev4jep5n4gvvqx5sxsne ; ssn:deployedOnPlatform bdr:rqefuczecfce7lg3neucpuxfve ;
    bed:environment bedv:environment-borehole ; bed:sensorStatus bedv:borehole-status-open .
"""),
}

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
}


def expand(curie: str) -> URIRef:
    ns, local = curie.split(":")
    return URIRef({"bdr": "https://example.org/bedretto/id/", "bedv": "https://example.org/bedretto/vocab/"}[ns] + local)


def results(data: Graph, shapes: Path):
    conforms, report, _ = validate(
        data_graph=data,
        shacl_graph=Graph().parse(shapes, format="turtle"),
        advanced=True,
        inference="none",
    )
    out = []
    for r in report.subjects(SH.focusNode, None):
        out.append((report.value(r, SH.focusNode), str(report.value(r, SH.sourceConstraintComponent)).rsplit("#")[-1]))
    return conforms, out


def main() -> int:
    failures = 0

    for shapes in (v.SHAPES, v.VOCAB_SHAPES, ROOT / "ontology" / "crate" / "crate-shapes.ttl"):
        conforms, _, text = validate(Graph().parse(shapes, format="turtle"), meta_shacl=True, advanced=True)
        print(f"meta-shacl {shapes.name}: {'ok' if conforms else text}")

    base = v.union_graph(v.load_dataset())
    base.parse(data=PREFIXES + VALID, format="turtle")
    conforms, res = results(base, v.SHAPES)
    print(f"valid fixtures: {'CONFORMS' if conforms else res}")
    failures += not conforms

    for name, (focus, component, ttl) in INVALID.items():
        g = Graph() + base
        g.parse(data=PREFIXES + ttl, format="turtle")
        _, res = results(g, v.SHAPES)
        hit = (expand(focus), component) in res
        print(f"{'ok  ' if hit else 'MISS'} {name}: {sorted(set(c for f, c in res if f == expand(focus)))}")
        failures += not hit

    vocab = Graph().parse(v.VOCAB, format="turtle")
    for name, (focus, component, ttl) in SKOS_INVALID.items():
        g = Graph() + vocab
        g.parse(data=PREFIXES + ttl, format="turtle")
        _, res = results(g, v.VOCAB_SHAPES)
        hit = (expand(focus), component) in res
        print(f"{'ok  ' if hit else 'MISS'} skos {name}: {sorted(set(c for f, c in res if f == expand(focus)))}")
        failures += not hit

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
