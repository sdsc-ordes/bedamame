import argparse
import sys
from pathlib import Path

from rdflib import Dataset, URIRef

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "bedretto.trig"
BEDRETTO = ROOT / "ontology" / "bedretto"
GRAPH_NS = "https://example.org/bedretto/graph/"

# loaded as named graphs next to the data, so queries can join terms, labels and shapes
STATIC_GRAPHS = {
    "ontology": BEDRETTO / "bedretto-ontology.ttl",
    "vocab": BEDRETTO / "bedretto-vocab.ttl",
    "shapes": BEDRETTO / "bedretto-shapes.ttl",
}

PREFIXES = """
PREFIX bed:     <https://example.org/bedretto/terms#>
PREFIX bedv:    <https://example.org/bedretto/vocab/>
PREFIX bedsh:   <https://example.org/bedretto/shapes#>
PREFIX gr:      <https://example.org/bedretto/graph/>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
PREFIX sh:      <http://www.w3.org/ns/shacl#>
PREFIX schema:  <https://schema.org/>
PREFIX skos:    <http://www.w3.org/2004/02/skos/core#>
PREFIX prov:    <http://www.w3.org/ns/prov#>
PREFIX ssn:     <http://www.w3.org/ns/ssn/>
PREFIX qudt:    <http://qudt.org/schema/qudt/>
PREFIX time:    <http://www.w3.org/2006/time#>
"""

QUERIES: dict[str, str] = {}


def q(name: str, sparql: str) -> None:
    QUERIES[name] = PREFIXES + sparql


q(
    "current-collar-position",
    """
SELECT ?borehole ?surveyType ?easting ?northing ?elevation ?assertedOn ?by
WHERE {
    GRAPH ?g {
        ?survey a bed:CollarSurvey ;
                bed:ofBorehole  ?bh ;
                bed:surveyType  ?type ;
                bed:easting     ?easting ;
                bed:northing    ?northing ;
                bed:elevation   ?elevation .
    }
    GRAPH gr:register-boreholes { ?bh schema:name ?borehole }
    GRAPH gr:vocab { ?type skos:prefLabel ?surveyType }
    GRAPH gr:provenance {
        ?g prov:generatedAtTime ?assertedOn ;
           prov:wasAttributedTo ?agent .
    }
    GRAPH gr:register-agents { ?agent schema:name ?by }

    FILTER (?borehole = "BFE_A_01")

    FILTER NOT EXISTS {
        GRAPH ?later { ?other a bed:CollarSurvey ; bed:ofBorehole ?bh }
        GRAPH gr:provenance { ?later prov:generatedAtTime ?laterDate }
        FILTER (?laterDate > ?assertedOn)
    }
}
""",
)

q(
    "hydromechanical-deployments",
    """
SELECT ?sensor ?kind ?serial ?borehole ?depth_m ?coupling ?installed
WHERE {
    GRAPH gr:vocab {
        ?type skos:broader* bedv:sensor-type-hydromechanical ;
              skos:prefLabel ?kind .
    }
    GRAPH gr:register-sensors {
        ?s bed:sensorKind    ?type ;
           schema:name       ?sensor ;
           bed:serialNumber  ?serial .
    }
    GRAPH ?g {
        ?depl a ssn:Deployment ;
              ssn:deployedSystem     ?s ;
              ssn:deployedOnPlatform ?bh ;
              bed:servesExperiment   ?exp ;
              bed:coupling           ?coup .
        OPTIONAL { ?depl bed:measuredDepth [ qudt:numericValue ?depth_m ] }
        OPTIONAL { ?depl time:hasTime [ time:hasBeginning [ time:inXSDDate ?installed ] ] }
    }
    GRAPH ?eg { ?exp a bed:Experiment ; schema:name "FEAR-2" }
    GRAPH gr:register-boreholes { ?bh schema:name ?borehole }
    GRAPH gr:vocab { ?coup skos:prefLabel ?coupling }
}
ORDER BY ?sensor
""",
)

q(
    "provenance-of-a-value",
    """
SELECT ?borehole ?easting ?graph ?label ?when ?who
WHERE {
    GRAPH ?graph {
        ?survey a bed:CollarSurvey ;
                bed:ofBorehole ?bh ;
                bed:easting    ?easting .
    }
    GRAPH gr:register-boreholes { ?bh schema:name ?borehole }
    GRAPH gr:provenance {
        ?graph schema:name          ?label ;
               prov:generatedAtTime ?when ;
               prov:wasAttributedTo ?agent .
    }
    GRAPH gr:register-agents { ?agent schema:name ?who }
}
ORDER BY ?borehole ?when
""",
)

q(
    "graphs-and-what-they-assert",
    """
SELECT ?graph ?label ?when
       (GROUP_CONCAT(DISTINCT ?name ; separator=", ") AS ?attributedTo)
       (COUNT(DISTINCT ?s) AS ?subjects)
WHERE {
    GRAPH gr:provenance {
        ?graph a prov:Bundle ;
               schema:name          ?label ;
               prov:generatedAtTime ?when ;
               prov:wasAttributedTo ?agent .
    }
    GRAPH gr:register-agents { ?agent schema:name ?name }
    GRAPH ?graph { ?s ?p ?o }
}
GROUP BY ?graph ?label ?when
ORDER BY ?when
""",
)

q(
    "describe-borehole",
    """
SELECT ?property ?value
WHERE {
    GRAPH gr:register-boreholes { ?bh schema:name "BFE_D_31" ; ?p ?o }
    GRAPH gr:ontology { ?p rdfs:label ?property }

    OPTIONAL { GRAPH gr:vocab { ?o skos:prefLabel ?concept } }
    OPTIONAL { GRAPH gr:register-testbeds { ?o schema:name ?testBed } }
    OPTIONAL {
        GRAPH gr:register-boreholes { ?o qudt:numericValue ?num ; qudt:hasUnit ?unit }
        BIND (CONCAT(STR(?num), " ", REPLACE(STR(?unit), "^.*/", "")) AS ?quantity)
    }
    OPTIONAL {
        GRAPH gr:register-boreholes {
            ?o time:hasBeginning/time:inXSDDate ?from ;
               time:hasEnd/time:inXSDDate       ?to .
        }
        BIND (CONCAT(STR(?from), " to ", STR(?to)) AS ?interval)
    }
    BIND (COALESCE(?concept, ?testBed, ?quantity, ?interval, ?o) AS ?value)
}
ORDER BY ?property
""",
)

q(
    "vocabulary-in-use",
    """
SELECT ?property ?scheme (COUNT(DISTINCT ?concept) AS ?concepts) (COUNT(DISTINCT ?used) AS ?inUse)
WHERE {
    GRAPH gr:shapes { ?shape sh:path ?p ; bedsh:inScheme ?s }
    GRAPH gr:vocab  { ?s skos:prefLabel ?scheme . ?concept skos:inScheme ?s }

    OPTIONAL { GRAPH gr:ontology { ?p rdfs:label ?label } }
    BIND (COALESCE(?label, REPLACE(STR(?p), "^.*[/#]", "")) AS ?property)

    OPTIONAL {
        GRAPH ?g { ?record ?p ?concept }
        BIND (?concept AS ?used)
    }
}
GROUP BY ?property ?scheme
ORDER BY DESC(?inUse) ?property
""",
)


def load() -> Dataset:
    ds = Dataset()
    ds.parse(DATA, format="trig")
    for name, path in STATIC_GRAPHS.items():
        ds.graph(URIRef(GRAPH_NS + name)).parse(path, format="turtle")
    return ds


def shorten(value: object) -> str:
    return str(value).replace(GRAPH_NS, "gr:")


def run_one(ds: Dataset, name: str) -> int:
    print(f"\n{name}")
    rows = list(ds.query(QUERIES[name]))
    if not rows:
        print("  (no rows)")
        return 1

    headers = [str(v) for v in rows[0].labels]
    table = [[shorten(r[h]) if r[h] is not None else "" for h in headers] for r in rows]
    widths = [
        max(len(h), *(len(row[i]) for row in table)) for i, h in enumerate(headers)
    ]

    print("  " + "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  " + "  ".join("-" * w for w in widths))
    for row in table:
        print("  " + "  ".join(c.ljust(widths[i]) for i, c in enumerate(row)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="list the queries")
    ap.add_argument("--run", metavar="NAME", help="run one query")
    ap.add_argument("--all", action="store_true", help="run every query")
    ap.add_argument(
        "--show", metavar="NAME", help="print the SPARQL without running it"
    )
    args = ap.parse_args()

    if args.list or not (args.run or args.all or args.show):
        print("\n".join(QUERIES))
        return 0

    if args.show:
        print(QUERIES[args.show])
        return 0

    ds = load()
    if args.all:
        return max(run_one(ds, n) for n in QUERIES)

    if args.run not in QUERIES:
        print(f"unknown query: {args.run}", file=sys.stderr)
        print(f"available: {', '.join(QUERIES)}", file=sys.stderr)
        return 2
    return run_one(ds, args.run)


if __name__ == "__main__":
    sys.exit(main())
