import argparse
import sys
from pathlib import Path

from pyshacl import validate
from rdflib import Dataset, Graph, URIRef

import config

ROOT = Path(__file__).resolve().parent.parent
# converted from openBIS by openbis_to_rdf.py
DATA = ROOT / "out" / "bedretto.trig"
BEDRETTO = ROOT / "ontology" / "bedretto"
ONTOLOGY = BEDRETTO / "bedretto-ontology.ttl"
VOCAB = BEDRETTO / "bedretto-vocab.ttl"
SHAPES = BEDRETTO / "bedretto-shapes.ttl"
VOCAB_SHAPES = ROOT / "ontology" / "skos" / "skos-shapes.ttl"


def load_dataset(path: Path = DATA) -> Dataset:
    ds = Dataset()
    ds.parse(path, format="trig")
    return ds


def union_graph(ds: Dataset) -> Graph:
    g = Graph()
    for s, p, o, _ in ds.quads((None, None, None, None)):
        g.add((s, p, o))
    g.parse(ONTOLOGY, format="turtle")
    g.parse(VOCAB, format="turtle")
    return g


def break_one_crs(g: Graph) -> URIRef | None:
    prop = URIRef(config.TERMS + "coordinateSystem")
    for subject, _, _ in g.triples((None, prop, None)):
        g.remove((subject, prop, None))
        return subject
    return None


def run(data: Graph, shapes_path: Path) -> tuple[bool, str]:
    conforms, _, text = validate(
        data_graph=data,
        shacl_graph=Graph().parse(shapes_path, format="turtle"),
        advanced=True,
        inference="none",
        meta_shacl=False,
    )
    return conforms, text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=DATA)
    ap.add_argument(
        "--demo-failure",
        action="store_true",
        help="remove the CRS from one collar survey before validating",
    )
    args = ap.parse_args()

    data = union_graph(load_dataset(args.data))
    if args.demo_failure:
        print(f"removed bed:coordinateSystem from <{break_one_crs(data)}>")

    conforms, text = run(data, SHAPES)
    print("store: CONFORMS" if conforms else text.rstrip())

    vocab_conforms, vocab_text = run(
        Graph().parse(VOCAB, format="turtle"), VOCAB_SHAPES
    )
    print("vocab: CONFORMS" if vocab_conforms else vocab_text.rstrip())

    if args.demo_failure:
        conforms = not conforms
    return 0 if conforms and vocab_conforms else 1


if __name__ == "__main__":
    sys.exit(main())
