import argparse
import sys
from pathlib import Path

from rdflib import Dataset, URIRef

import config

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "out" / "bedretto.trig"
BEDRETTO = ROOT / "ontology" / "bedretto"
GRAPH_NS = config.GRAPH

# loaded as named graphs next to the data, so queries can join terms, labels and shapes. Data graphs are
# openBIS collections, whose paths differ between instances, so queries find records by class.
STATIC_GRAPHS = {
    "ontology": BEDRETTO / "bedretto-ontology.ttl",
    "vocab": BEDRETTO / "bedretto-vocab.ttl",
    "shapes": BEDRETTO / "bedretto-shapes.ttl",
}

PREFIXES = "\n" + config.sparql_prefixes(
    "bed", "bedv", "bedsh", "gr", "rdfs", "sh", "schema", "skos", "prov", "ssn", "qudt"
)

QUERIES: dict[str, str] = {}


def q(name: str, sparql: str) -> None:
    QUERIES[name] = PREFIXES + sparql


q(
    "current-collar-position",
    """
SELECT ?borehole ?surveyType ?easting ?northing ?elevation ?surveyed
       (GROUP_CONCAT(?name ; separator=", ") AS ?by)
WHERE {
    GRAPH ?g {
        ?survey a bed:CollarSurvey ;
                bed:ofBorehole  ?bh ;
                bed:surveyType  ?type ;
                bed:surveyDate  ?surveyed ;
                bed:easting     ?easting ;
                bed:northing    ?northing ;
                bed:elevation   ?elevation .
        OPTIONAL { ?survey bed:surveyedBy ?agent }
    }
    GRAPH ?bg { ?bh a bed:Borehole ; schema:name ?borehole }
    GRAPH gr:vocab { ?type skos:prefLabel ?surveyType }
    OPTIONAL { GRAPH ?ag { ?agent schema:name ?name } }

    FILTER (?borehole = "BFE_A_01")

    FILTER NOT EXISTS {
        GRAPH ?later { ?other a bed:CollarSurvey ; bed:ofBorehole ?bh ; bed:surveyDate ?laterDate }
        FILTER (?laterDate > ?surveyed)
    }
}
GROUP BY ?borehole ?surveyType ?easting ?northing ?elevation ?surveyed
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
    GRAPH ?sg {
        ?s bed:sensorKind    ?type ;
           schema:name       ?sensor ;
           schema:serialNumber ?serial .
    }
    GRAPH ?g {
        ?depl a ssn:Deployment ;
              ssn:deployedSystem     ?s ;
              ssn:deployedOnPlatform ?bh ;
              bed:servesExperiment   ?exp ;
              bed:coupling           ?coup .
        OPTIONAL { ?depl bed:measuredDepth [ qudt:numericValue ?depth_m ] }
        OPTIONAL { ?depl bed:deployedOn ?installed }
    }
    GRAPH ?eg { ?exp a bed:Experiment ; schema:name "FEAR-2" }
    GRAPH ?bg { ?bh a bed:Borehole ; schema:name ?borehole }
    GRAPH gr:vocab { ?coup skos:prefLabel ?coupling }
}
ORDER BY ?sensor
""",
)

q(
    "provenance-of-a-value",
    """
SELECT ?borehole ?easting ?surveyed ?surveyedBy ?graph ?recorded ?recordedBy
WHERE {
    GRAPH ?graph {
        ?survey a bed:CollarSurvey ;
                bed:ofBorehole ?bh ;
                bed:easting    ?easting ;
                bed:surveyDate ?surveyed .
        OPTIONAL { ?survey bed:surveyedBy ?agent }
    }
    GRAPH ?bg { ?bh a bed:Borehole ; schema:name ?borehole }
    OPTIONAL { GRAPH ?ag { ?agent schema:name ?surveyedBy } }
    GRAPH gr:provenance {
        ?graph prov:generatedAtTime ?recorded ;
               prov:wasAttributedTo ?user .
        ?user schema:name ?recordedBy .
    }
    FILTER (?borehole = "BFE_A_01")
}
ORDER BY ?borehole ?surveyed
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
        ?agent schema:name ?name .
    }
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
    GRAPH ?g { ?bh a bed:Borehole ; schema:name "BFE_D_31" ; ?p ?o }
    GRAPH gr:ontology { ?p rdfs:label ?property }

    OPTIONAL { GRAPH gr:vocab { ?o skos:prefLabel ?concept } }
    OPTIONAL { GRAPH ?tg { ?o a bed:TestBed ; schema:name ?testBed } }
    OPTIONAL {
        GRAPH ?g { ?o qudt:numericValue ?num ; qudt:hasUnit ?unit }
        BIND (CONCAT(STR(?num), " ", REPLACE(STR(?unit), "^.*/", "")) AS ?quantity)
    }
    BIND (COALESCE(?concept, ?testBed, ?quantity, ?o) AS ?value)
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


def load(path: Path = DATA) -> Dataset:
    ds = Dataset()
    ds.parse(path, format="trig")
    for name, path in STATIC_GRAPHS.items():
        ds.graph(URIRef(GRAPH_NS + name)).parse(path, format="turtle")
    return ds


def shorten(value: object) -> str:
    return str(value).replace(GRAPH_NS, "gr:")


def select(ds: Dataset, name: str) -> tuple[list[str], list[list[str]]]:
    result = ds.query(QUERIES[name])
    headers = [str(v) for v in result.vars]
    return headers, [
        [shorten(r[h]) if r[h] is not None else "" for h in headers] for r in result
    ]


def run_one(ds: Dataset, name: str) -> int:
    print(f"\n{name}")
    headers, table = select(ds, name)
    if not table:
        print("  (no rows)")
        return 1

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
    ap.add_argument("--data", type=Path, default=DATA)
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

    ds = load(args.data)
    if args.all:
        return max(run_one(ds, n) for n in QUERIES)

    if args.run not in QUERIES:
        print(f"unknown query: {args.run}", file=sys.stderr)
        print(f"available: {', '.join(QUERIES)}", file=sys.stderr)
        return 2
    return run_one(ds, args.run)


if __name__ == "__main__":
    sys.exit(main())
