import csv
from pathlib import Path

# The one base IRI of everything Bedretto publishes; `just set-base URL` rewrites it everywhere
BASE = "https://example.org/bedretto/"
VERSION = "0.4.0"

TERMS = BASE + "terms#"
VOCAB = BASE + "vocab/"
SHAPES = BASE + "shapes#"
ID = BASE + "id/"
GRAPH = BASE + "graph/"

ONTOLOGY = BASE + "terms"
ONTOLOGY_VERSION = f"{ONTOLOGY}/{VERSION}"

# the lab's own openBIS object types; everything else is an ELN default
BEDRETTO_TYPES = [
    "BOREHOLES", "BOREHOLE_LOGGING",
    "CORES", "CORE_REQUEST", "IGSN_CORE",
    "SENSORS", "SEIS_SENSOR", "SENSOR_INSTAL", "SEIS_SENSOR_INSTAL",
    "DATALOGGER", "DEVICE", "METHOD",
]  # fmt: skip

# types the Phase 3 changes add or extend; annotated like the 12
ANNOTATED_TYPES = BEDRETTO_TYPES + [
    "PERSON", "ORGANIZATION", "TESTBED", "BOREHOLE_MOUTH_SURVEY", "SENSOR_POSITION",
]  # fmt: skip

NAMESPACES = {
    "bed": TERMS,
    "bedv": VOCAB,
    "bedsh": SHAPES,
    "bdr": ID,
    "gr": GRAPH,
    "schema": "https://schema.org/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "sh": "http://www.w3.org/ns/shacl#",
    "dcterms": "http://purl.org/dc/terms/",
    "sosa": "http://www.w3.org/ns/sosa/",
    "ssn": "http://www.w3.org/ns/ssn/",
    "prov": "http://www.w3.org/ns/prov#",
    "geo": "http://www.opengis.net/ont/geosparql#",
    "time": "http://www.w3.org/2006/time#",
    "qudt": "http://qudt.org/schema/qudt/",
    "unit": "http://qudt.org/vocab/unit/",
    "quantitykind": "http://qudt.org/vocab/quantitykind/",
    "epsg": "http://www.opengis.net/def/crs/EPSG/0/",
}

# openBIS type and field -> term, unit and scheme; read by the converter and the annotation generator
MAPPING = Path(__file__).resolve().parent.parent / "mapping" / "openbis-annotations.csv"

# openBIS semantic annotations: Ontology Id and Ontology Version per prefix; the Ontology Annotation Id
# is the full term IRI. schema.org as on openBIS 7.0's own PUBLICATION type; RDFS, SOSA, SSN and Dublin
# Core publish no version IRI, so their version is the namespace.
ANNOTATION_SOURCES = {
    "bed": (ONTOLOGY, ONTOLOGY_VERSION),
    "schema": ("https://schema.org/", "https://schema.org/version/28.1"),
    "rdfs": (NAMESPACES["rdfs"], NAMESPACES["rdfs"]),
    "sosa": (NAMESPACES["sosa"], NAMESPACES["sosa"]),
    "ssn": (NAMESPACES["ssn"], NAMESPACES["ssn"]),
    "dcterms": (NAMESPACES["dcterms"], NAMESPACES["dcterms"]),
}


def expand(curie: str) -> str:
    prefix, local = curie.split(":", 1)
    return NAMESPACES[prefix] + local


def sparql_prefixes(*names: str) -> str:
    return "".join(f"PREFIX {n + ':':<14}<{NAMESPACES[n]}>\n" for n in names)


def turtle_prefixes(*names: str) -> str:
    return "".join(f"@prefix {n + ':':<14}<{NAMESPACES[n]}> .\n" for n in names)


def load_mapping(path: Path = MAPPING) -> dict[tuple[str, str], dict]:
    # keyed by (object type, property code), "" for the type itself
    with path.open() as f:
        return {(r["object_type"], r["property_code"]): r for r in csv.DictReader(f)}
