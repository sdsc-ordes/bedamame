import argparse
import sys
from pathlib import Path

from pyshacl import validate
from rdflib import Dataset, Graph
from rdflib.namespace import SH

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


def run(data: Graph, shapes_path: Path) -> tuple[bool, str, list[str]]:
    # warnings (values that contradict each other) are listed but do not fail validation
    conforms, report, text = validate(
        data_graph=data,
        shacl_graph=Graph().parse(shapes_path, format="turtle"),
        advanced=True,
        inference="none",
        meta_shacl=False,
        allow_warnings=True,
    )
    warnings = sorted(
        str(report.value(r, SH.resultMessage))
        for r in report.subjects(SH.resultSeverity, SH.Warning)
    )
    return conforms, text, warnings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=DATA)
    args = ap.parse_args()

    ok = True
    for name, data, shapes in [
        ("store", union_graph(load_dataset(args.data)), SHAPES),
        ("vocab", Graph().parse(VOCAB, format="turtle"), VOCAB_SHAPES),
    ]:
        conforms, text, warnings = run(data, shapes)
        for w in warnings:
            print(f"warning: {w}")
        print(f"{name}: CONFORMS" if conforms else text.rstrip())
        ok = ok and conforms
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
