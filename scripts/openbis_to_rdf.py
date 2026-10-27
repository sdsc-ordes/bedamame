import argparse
import csv
import datetime
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from rdflib import BNode, Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, SH, SKOS, XSD

import config
import validate as v

ROOT = Path(__file__).resolve().parent.parent
EXPORT = ROOT / "tests" / "fixtures" / "openbis-export.json"
OUT = ROOT / "out" / "bedretto.trig"
TERMS = ROOT / "mapping" / "openbis-terms.csv"
COLLECTIONS = ROOT / "mapping" / "collections.csv"

BED = Namespace(config.TERMS)
GR = Namespace(config.GRAPH)
ID = Namespace(config.ID)
PROV = Namespace(config.NAMESPACES["prov"])
QUDT = Namespace(config.NAMESPACES["qudt"])
SCHEMA = Namespace(config.NAMESPACES["schema"])

# the literal an openBIS data type gives when the shapes say nothing else
DATATYPES = {
    "DATE": XSD.date,
    "TIMESTAMP": XSD.dateTime,
    "REAL": XSD.decimal,
    "INTEGER": XSD.integer,
    "BOOLEAN": XSD.boolean,
}


def norm(text: str) -> str:
    return " ".join(str(text).split()).casefold()


def as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def timestamp(text: str) -> datetime.datetime:
    # V3 writes TIMESTAMPs as yyyy-MM-dd HH:mm:ss Z, e.g. 2025-11-25 00:00:00 +0100
    return datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S %z")


def literal(text: str, datatype: URIRef | None) -> Literal:
    if datatype == XSD.date:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}( .*)?", text):
            raise ValueError(f"not a date: {text!r}")
        return Literal(text[:10], datatype=XSD.date)
    if datatype == XSD.dateTime:
        return Literal(timestamp(text).isoformat(), datatype=XSD.dateTime)
    if datatype == XSD.decimal:
        return Literal(Decimal(text))
    if datatype == XSD.integer:
        return Literal(int(Decimal(text)))
    if datatype == XSD.boolean:
        return Literal(text.lower() == "true")
    return Literal(text)


class Converter:
    def __init__(self, export: dict):
        self.export = export
        self.mapping = config.load_mapping()
        with TERMS.open() as f:
            self.terms = {
                (r["vocabulary_code"], r["term_code"]): r["concept"]
                for r in csv.DictReader(f)
            }
        with COLLECTIONS.open() as f:
            self.collections = list(csv.DictReader(f))
        vocab = Graph().parse(v.VOCAB, format="turtle")
        self.labels: dict[str, dict[str, URIRef]] = {}
        for concept, scheme in vocab.subject_objects(SKOS.inScheme):
            for p in (SKOS.prefLabel, SKOS.altLabel, SKOS.hiddenLabel):
                for label in vocab.objects(concept, p):
                    self.labels.setdefault(str(scheme), {})[norm(label)] = concept
        shapes = Graph().parse(v.SHAPES, format="turtle")
        self.datatypes = {
            shapes.value(s, SH.path): dt
            for s, dt in shapes.subject_objects(SH.datatype)
        }
        self.ds = Dataset()
        self.problems: list[str] = []

    def concept(self, scheme: str, vocabulary: str | None, value: str) -> URIRef | None:
        if vocabulary:
            curie = self.terms.get((vocabulary, value))
            return URIRef(config.expand(curie)) if curie else None
        return self.labels.get(config.expand(scheme), {}).get(norm(value))

    def values(self, g: Graph, o: dict, code: str, raw, m: dict) -> list:
        prop = self.export["types"][o["type"]]["properties"][code]
        term = URIRef(config.expand(m["term"]))
        out = []
        for value in as_list(raw):
            if prop["dataType"] == "SAMPLE":
                out.append(ID[value])
            elif m["unit"]:
                q = BNode()
                g.add((q, RDF.type, QUDT.QuantityValue))
                g.add((q, QUDT.numericValue, Literal(Decimal(value))))
                g.add((q, QUDT.hasUnit, URIRef(config.expand(m["unit"]))))
                out.append(q)
            elif m["scheme"]:
                if c := self.concept(m["scheme"], prop["vocabulary"], value):
                    out.append(c)
                else:
                    self.problems.append(
                        f"{o['identifier']} {code}: no concept for {value!r}"
                    )
            elif term == BED.tunnelMeter and prop["dataType"] == "REAL":
                out.append(Literal(f"TM{int(Decimal(value))}"))
            else:
                datatype = self.datatypes.get(term) or DATATYPES.get(prop["dataType"])
                try:
                    out.append(literal(value, datatype))
                except (ValueError, InvalidOperation):
                    self.problems.append(
                        f"{o['identifier']} {code}: {value!r} is not {datatype}"
                    )
        return out

    def graph_of(self, o: dict) -> URIRef:
        return GR[(o["collection"] or o["project"]).strip("/")]

    def experiment_of(self, path: str) -> dict | None:
        rows = [
            r
            for r in self.collections
            if f"{path}/".startswith(r["openbis_path"] + "/")
        ]
        return max(rows, key=lambda r: len(r["openbis_path"]), default=None)

    def experiment(self, row: dict) -> URIRef:
        iri = ID[f"experiment/{row['experiment']}"]
        g = self.ds.graph(GR.experiments)
        g.add((iri, RDF.type, BED.Experiment))
        g.add((iri, SCHEMA.name, Literal(row["experiment"])))
        if row["project"]:
            g.add((iri, BED.project, Literal(row["project"])))
        return iri

    def user(self, user_id: str) -> URIRef:
        iri = ID[f"user/{user_id}"]
        g = self.ds.graph(GR.provenance)
        g.add((iri, RDF.type, PROV.Agent))
        g.add((iri, SCHEMA.name, Literal(self.export["users"][user_id]["name"])))
        return iri

    def object(self, o: dict) -> None:
        g = self.ds.graph(self.graph_of(o))
        s = ID[o["permId"]]
        names = []
        kind = self.mapping.get((o["type"], ""))
        if kind and kind["term"]:
            g.add((s, RDF.type, URIRef(config.expand(kind["term"]))))
        for code, raw in o["properties"].items():
            m = self.mapping.get((o["type"], code))
            if m is None:
                self.problems.append(f"{o['type']} {code}: not in {config.MAPPING.name}")
                continue
            if not m["term"]:
                continue
            term = URIRef(config.expand(m["term"]))
            for value in self.values(g, o, code, raw, m):
                if term == SCHEMA.name:
                    names.append(value)
                else:
                    g.add((s, term, value))
        g.add((s, SCHEMA.name, names[0] if names else Literal(o["code"])))
        if kind and kind["term"] == "ssn:Deployment":
            if row := self.experiment_of(o["collection"] or o["project"]):
                g.add((s, BED.servesExperiment, self.experiment(row)))

    def bundles(self) -> None:
        g = self.ds.graph(GR.provenance)
        by_graph: dict[URIRef, list[dict]] = {}
        for o in self.export["objects"]:
            by_graph.setdefault(self.graph_of(o), []).append(o)
        for graph, objects in sorted(by_graph.items()):
            path = objects[0]["collection"] or objects[0]["project"]
            row = self.experiment_of(path)
            collection = self.export["collections"].get(path, {})
            # a campaign named for exactly this collection, else the collection's own name
            name = row["campaign"] if row and row["openbis_path"] == path else None
            g.add((graph, RDF.type, PROV.Bundle))
            g.add((graph, SCHEMA.name, Literal(name or collection.get("name") or path)))
            latest = max(o["modificationDate"] for o in objects)
            g.add((graph, PROV.generatedAtTime, Literal(latest, datatype=XSD.dateTime)))
            for user_id in sorted({o["registrator"] for o in objects}):
                g.add((graph, PROV.wasAttributedTo, self.user(user_id)))

    def run(self) -> Dataset:
        for o in self.export["objects"]:
            self.object(o)
        self.bundles()
        return self.ds


def convert(export: dict) -> tuple[Dataset, list[str]]:
    c = Converter(export)
    return c.run(), c.problems


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Convert an openBIS V3 dump (openbis_api.py --dump) to Bedretto RDF"
    )
    ap.add_argument("--export", type=Path, default=EXPORT)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    ds, problems = convert(json.loads(args.export.read_text()))
    for p in problems:
        print(f"warning: {p}", file=sys.stderr)
    for prefix in (
        "bed",
        "bedv",
        "bdr",
        "gr",
        "schema",
        "rdfs",
        "xsd",
        "sosa",
        "ssn",
        "prov",
        "qudt",
        "unit",
    ):
        ds.bind(prefix, config.NAMESPACES[prefix])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    ds.serialize(args.out, format="trig")
    graphs = [g for g in ds.graphs() if len(g)]
    print(f"{args.out}: {sum(len(g) for g in graphs)} triples in {len(graphs)} graphs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
