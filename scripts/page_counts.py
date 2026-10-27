import re
import sys
from pathlib import Path

from rdflib import OWL, RDF, Graph
from rdflib.namespace import SKOS

import config
import openbis_changes
import validate as v

PAGE = Path(__file__).resolve().parent.parent / "architecture" / "index.html"
# an element of the page whose text is a count: <b data-count="classes">19</b>. The key is one of
# counts() below, or the local name of a concept scheme, for the number of its concepts.
COUNT = re.compile(r'(data-count="([^"]+)">)[^<]*(<)')


def counts() -> dict[str, str]:
    ontology = Graph().parse(v.ONTOLOGY, format="turtle")
    vocab = Graph().parse(v.VOCAB, format="turtle")
    mapping = config.load_mapping().values()
    schemes = set(vocab.subjects(RDF.type, SKOS.ConceptScheme))
    out = {
        "version": config.VERSION,
        "classes": sum(str(c).startswith(config.TERMS) for c in ontology.subjects(RDF.type, OWL.Class)),
        "vocabularies": len(schemes),
        "types": sum(r["kind"] == "type" for r in mapping),
        "annotations": sum(bool(r["term"]) for r in mapping),
        "changes": len(openbis_changes.CHANGES),
    }  # fmt: skip
    for s in schemes:
        out[str(s).removeprefix(config.VOCAB)] = len(set(vocab.subjects(SKOS.inScheme, s)))
    return {k: str(n) for k, n in out.items()}


def fill(page: str) -> str:
    c = counts()
    return COUNT.sub(lambda m: m[1] + c[m[2]] + m[3], page)


def main() -> int:
    page = PAGE.read_text()
    new = fill(page)
    PAGE.write_text(new)
    print(f"{PAGE.name}: {'updated' if new != page else 'already current'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
