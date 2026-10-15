import argparse
import datetime
import json
import sys
from collections import defaultdict
from pathlib import Path

from pyshacl import validate
from rdflib import Dataset, Graph, Literal, URIRef
from rdflib.namespace import RDF

import config

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "bedretto.trig"
CRATE_SHAPES = ROOT / "ontology" / "crate" / "crate-shapes.ttl"
OUT_DIR = ROOT / "out"

ID = config.ID
TERMS = config.TERMS
GRAPH_NS = config.GRAPH
SCHEMA = config.NAMESPACES["schema"]

PROFILE = "https://w3id.org/bedretto/profile/experiment/0.1"
LICENCE = "https://creativecommons.org/licenses/by/4.0/"
CRATE_BASE = config.BASE + "crate/"

SELECTED = [
    GRAPH_NS + "campaign-fear2-install",
    GRAPH_NS + "survey-flotron-2024-09-08",
]

STUB_PROPS = {
    SCHEMA + "name",
    SCHEMA + "manufacturer",
    SCHEMA + "serialNumber",
    TERMS + "nickname",
    TERMS + "totalLength",
    TERMS + "boreholeGeometry",
}

NAMESPACES = {
    p: config.NAMESPACES[p]
    for p in ("bed", "sosa", "ssn", "prov", "geo", "qudt", "skos", "time")
}

CONTEXT = ["https://w3id.org/ro/crate/1.2/context", NAMESPACES]

VALIDATION_CONTEXT = {
    "@vocab": "http://schema.org/",
    "conformsTo": "http://purl.org/dc/terms/conformsTo",
    **NAMESPACES,
}

COMPACT = {
    URIRef(SCHEMA + "name"): "name",
    URIRef(SCHEMA + "manufacturer"): "manufacturer",
    URIRef(SCHEMA + "serialNumber"): "serialNumber",
}


def load() -> Dataset:
    ds = Dataset()
    ds.parse(DATA, format="trig")
    return ds


def select_and_close(ds: Dataset) -> tuple[Graph, dict[str, int]]:
    out = Graph()
    counts: dict[str, int] = {}

    for uri in SELECTED:
        ctx = ds.graph(URIRef(uri))
        for triple in ctx:
            out.add(triple)
        counts[uri] = len(ctx)

    frontier = [o for _, _, o in out if not isinstance(o, (URIRef, Literal))]
    seen_bnodes = set()
    while frontier:
        node = frontier.pop()
        if node in seen_bnodes:
            continue
        seen_bnodes.add(node)
        for ctx in ds.graphs():
            for _, p, o in ctx.triples((node, None, None)):
                out.add((node, p, o))
                if not isinstance(o, (URIRef, Literal)):
                    frontier.append(o)

    described = {s for s in out.subjects() if isinstance(s, URIRef)}
    referenced = {o for o in out.objects() if isinstance(o, URIRef)}
    dangling = {r for r in referenced - described if str(r).startswith(ID)}

    stubs = 0
    for ref in dangling:
        for ctx in ds.graphs():
            for _, p, o in ctx.triples((ref, None, None)):
                if p == RDF.type or str(p) in STUB_PROPS:
                    out.add((ref, p, o))
                    if not isinstance(o, (URIRef, Literal)):
                        for _, p2, o2 in ctx.triples((o, None, None)):
                            out.add((o, p2, o2))
        if (ref, RDF.type, None) in out:
            stubs += 1

    counts["closure stubs"] = stubs
    return out, counts


def term(p: URIRef) -> str:
    if p in COMPACT:
        return COMPACT[p]
    for prefix, ns in NAMESPACES.items():
        if str(p).startswith(ns):
            return f"{prefix}:{str(p)[len(ns):]}"
    return str(p)


def node_id(node, g: Graph, skolem: dict) -> str:
    if isinstance(node, URIRef):
        return str(node)
    if node not in skolem:
        kinds = list(g.objects(node, RDF.type))
        base = (
            str(kinds[0]).rsplit("/", 1)[-1].rsplit("#", 1)[-1].lower()
            if kinds
            else "node"
        )
        skolem[node] = f"#{base}-{len(skolem) + 1}"
    return skolem[node]


def to_jsonld(g: Graph) -> list[dict]:
    skolem: dict = {}
    by_subject: dict[str, dict] = {}

    for s in set(g.subjects()):
        sid = node_id(s, g, skolem)
        entity = by_subject.setdefault(sid, {"@id": sid})
        grouped = defaultdict(list)
        for p, o in g.predicate_objects(s):
            if p == RDF.type:
                grouped["@type"].append(term(o))
            elif isinstance(o, Literal):
                if o.datatype and "integer" in str(o.datatype):
                    grouped[term(p)].append(int(o))
                elif o.datatype and "decimal" in str(o.datatype):
                    grouped[term(p)].append(float(o))
                else:
                    grouped[term(p)].append(str(o))
            else:
                grouped[term(p)].append({"@id": node_id(o, g, skolem)})
        for key, values in grouped.items():
            entity[key] = values[0] if len(values) == 1 else values

    return [by_subject[sid] for sid in sorted(by_subject)]


def build_crate(entities: list[dict], today: str) -> dict:
    descriptor = {
        "@id": "ro-crate-metadata.json",
        "@type": "CreativeWork",
        "conformsTo": {"@id": "https://w3id.org/ro/crate/1.2"},
        "about": {"@id": "./"},
    }
    root = {
        "@id": "./",
        "@type": "Dataset",
        "conformsTo": {"@id": PROFILE},
        "name": "FEAR-2 tiltmeter array, BedrettoLab",
        "description": (
            "Tiltmeter deployments for the FEAR-2 experiment at the Bedretto "
            "Underground Laboratory, with the collar survey of a host borehole."
        ),
        "license": {"@id": LICENCE},
        "datePublished": today,
        "bed:builtFromGraph": [{"@id": g} for g in SELECTED],
    }
    profile = {
        "@id": PROFILE,
        "@type": ["CreativeWork", "Profile"],
        "name": "BedrettoLab experiment crate profile",
        "version": "0.1",
    }
    return {"@context": CONTEXT, "@graph": [descriptor, root, profile, *entities]}


def check(crate: dict) -> tuple[bool, str]:
    offline = dict(crate)
    offline["@context"] = VALIDATION_CONTEXT
    g = Graph()
    g.parse(data=json.dumps(offline), format="json-ld", base=CRATE_BASE)
    conforms, _, text = validate(
        data_graph=g,
        shacl_graph=Graph().parse(CRATE_SHAPES, format="turtle"),
        advanced=True,
        inference="none",
    )
    return conforms, text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT_DIR / "ro-crate-metadata.json")
    ap.add_argument("--skip-validation", action="store_true")
    args = ap.parse_args()

    g, counts = select_and_close(load())
    for name, n in counts.items():
        print(f"{name.replace(GRAPH_NS, 'gr:'):<32} {n}")

    crate = build_crate(to_jsonld(g), datetime.date.today().isoformat())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(crate, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {args.out}: {len(crate['@graph'])} entities")

    if args.skip_validation:
        return 0
    conforms, text = check(crate)
    print("CONFORMS" if conforms else text.rstrip())
    return 0 if conforms else 1


if __name__ == "__main__":
    sys.exit(main())
