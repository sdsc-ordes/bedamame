from pathlib import Path

import pytest
from rdflib import OWL, RDF, RDFS, Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import SH, SKOS

import config
import validate as v

QUDT = Namespace(config.NAMESPACES["qudt"])
BEDSH = Namespace(config.SHAPES)


@pytest.fixture(scope="module")
def ontology() -> Graph:
    return Graph().parse(v.ONTOLOGY, format="turtle")


@pytest.fixture(scope="module")
def vocab() -> Graph:
    return Graph().parse(v.VOCAB, format="turtle")


@pytest.fixture(scope="module")
def shapes() -> Graph:
    return Graph().parse(v.SHAPES, format="turtle")


def iris(g: Graph | Dataset, namespace: str) -> set[URIRef]:
    quads = (
        g.quads((None, None, None, None))
        if isinstance(g, Dataset)
        else g.triples((None, None, None))
    )
    return {
        t
        for q in quads
        for t in q[:3]
        if isinstance(t, URIRef) and t.startswith(namespace)
    }


@pytest.mark.parametrize("path, header", [
    (v.ONTOLOGY, config.ONTOLOGY),
    (v.VOCAB, config.BASE + "vocab"),
    (v.SHAPES, config.BASE + "shapes"),
], ids=lambda x: x.name if isinstance(x, Path) else "")  # fmt: skip
def test_versions_match_config(path, header):
    g = Graph().parse(path, format="turtle")
    header = URIRef(header)
    assert g.value(header, OWL.versionInfo) == Literal(config.VERSION)
    assert g.value(header, OWL.versionIRI) == URIRef(f"{header}/{config.VERSION}")


def test_bed_terms_in_use_are_declared(ontology, vocab, shapes):
    declared = set(ontology.subjects(RDF.type, RDF.Property)) | set(
        ontology.subjects(RDF.type, RDFS.Class)
    )
    used = (
        iris(vocab, config.TERMS)
        | iris(shapes, config.TERMS)
        | iris(v.load_dataset(v.HANDWRITTEN), config.TERMS)
    )
    assert used - declared == set()


def test_concepts_in_use_are_declared(ontology, vocab, shapes):
    declared = set(vocab.subjects(RDF.type, SKOS.Concept)) | set(
        vocab.subjects(RDF.type, SKOS.ConceptScheme)
    )
    used = (
        iris(ontology, config.VOCAB)
        | iris(shapes, config.VOCAB)
        | iris(v.load_dataset(v.HANDWRITTEN), config.VOCAB)
    )
    assert used - declared - {URIRef(config.BASE + "vocab")} == set()


def test_bed_terms_have_label_and_definition(ontology):
    terms = set(ontology.subjects(RDF.type, RDF.Property)) | set(
        ontology.subjects(RDF.type, RDFS.Class)
    )
    missing = {
        t
        for t in terms
        if not (ontology.value(t, RDFS.label) and ontology.value(t, SKOS.definition))
    }
    assert missing == set()


def test_quantity_kind_exactly_on_quantity_valued_properties(ontology, shapes):
    quantity_valued = {
        shapes.value(s, SH.path)
        for s in shapes.subjects(SH.node, BEDSH.QuantityValueShape)
    }
    with_kind = set(ontology.subjects(QUDT.hasQuantityKind, None))
    assert quantity_valued == with_kind
