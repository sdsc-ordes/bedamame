import html
import subprocess
import sys
import tempfile
from pathlib import Path

from rdflib import OWL, RDF, Graph, URIRef
from rdflib.namespace import DCTERMS, SKOS

import config
import validate as v

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
# pyLODE 3.6.0 breaks with kurra >= 3.1; run apart from the project so its rdflib needs don't clash
PYLODE = ["uvx", "--from", "pylode==3.6.0", "--with", "kurra==3.0.5", "pylode"]
# the vocabulary's header metadata, copied onto each scheme
HEADER = [
    DCTERMS.creator,
    DCTERMS.created,
    DCTERMS.modified,
    DCTERMS.license,
    DCTERMS.source,
    OWL.versionInfo,
]


def pylode(profile: str, source: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [*PYLODE, "-p", profile, "-o", str(out), str(source)],
        check=True,
        capture_output=True,
    )


def schemes(vocab: Graph, folder: Path) -> list[tuple[str, str, Path]]:
    # VocPub documents one concept scheme per file
    header = URIRef(config.BASE + "vocab")
    out = []
    for scheme in vocab.subjects(RDF.type, SKOS.ConceptScheme):
        g = Graph(namespace_manager=vocab.namespace_manager)
        g += vocab.triples((scheme, None, None))
        for p in HEADER:
            for o in vocab.objects(header, p):
                g.add((scheme, p, o))
        for concept in vocab.subjects(SKOS.inScheme, scheme):
            g += vocab.triples((concept, None, None))
        name = str(scheme).removeprefix(config.VOCAB)
        source = folder / f"{name}.ttl"
        g.serialize(source, format="turtle")
        out.append((str(vocab.value(scheme, SKOS.prefLabel)), name, source))
    return sorted(out)


def index(pages: list[tuple[str, str]]) -> str:
    items = "".join(
        f'<li><a href="{href}">{html.escape(label)}</a></li>\n' for label, href in pages
    )
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        f"<title>Bedretto ontology {config.VERSION}</title></head><body>\n"
        f"<h1>Bedretto ontology {config.VERSION}</h1>\n"
        '<p><a href="ontology.html">Ontology</a>: classes and properties.</p>\n'
        f"<h2>Vocabularies</h2>\n<ul>\n{items}</ul>\n</body></html>\n"
    )


def main() -> int:
    pylode("ontpub", v.ONTOLOGY, SITE / "ontology.html")
    vocab = Graph().parse(v.VOCAB, format="turtle")
    pages = []
    with tempfile.TemporaryDirectory() as tmp:
        for label, name, source in schemes(vocab, Path(tmp)):
            pylode("vocpub", source, SITE / "vocab" / f"{name}.html")
            pages.append((label, f"vocab/{name}.html"))
    (SITE / "index.html").write_text(index(pages))
    print(f"{SITE}: ontology and {len(pages)} vocabularies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
