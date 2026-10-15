import html
import json
import re
import sys
from pathlib import Path

from rdflib import BNode, Graph, Literal, URIRef

ROOT = Path(sys.argv[1])
PAGE = Path(sys.argv[2])
sys.path.insert(0, str(ROOT / "scripts"))
import config  # noqa: E402
import openbis_to_rdf  # noqa: E402
import queries  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "openbis-export.json"
VOCAB = (ROOT / "ontology" / "bedretto" / "bedretto-vocab.ttl").read_text()
MAPPING = (ROOT / "mapping" / "openbis-annotations.csv").read_text().splitlines()
PREFIXES = ("bed", "bedv", "bdr", "schema", "sosa", "ssn", "prov", "qudt", "unit", "xsd", "dcterms", "rdfs")

# the converted fixture, with the ontology, vocabulary and shapes as graphs, as queries.py loads them
DS, _ = openbis_to_rdf.convert(json.loads(FIXTURE.read_text()))
for name, path in queries.STATIC_GRAPHS.items():
    DS.graph(URIRef(config.GRAPH + name)).parse(path, format="turtle")
NAME = URIRef(config.NAMESPACES["schema"] + "name")


def named(name: str) -> tuple[URIRef, URIRef]:
    # the subject called name, and its graph
    (found,) = [(s, g.identifier) for g in DS.graphs() for s in g.subjects(NAME, Literal(name))]
    return found


def describe(subject: URIRef, graph: URIRef) -> str:
    # one subject of one graph as Turtle, with its quantity values, indented as inside the graph
    g, sub = DS.graph(graph), Graph()
    for t in g.triples((subject, None, None)):
        sub.add(t)
        if isinstance(t[2], BNode):
            for u in g.triples((t[2], None, None)):
                sub.add(u)
    for prefix in PREFIXES:
        sub.bind(prefix, config.NAMESPACES[prefix])
    text = sub.serialize(format="turtle")
    body = "\n".join(line for line in text.splitlines() if not line.startswith("@prefix")).strip()
    return "\n".join("    " + line for line in body.splitlines())


def in_graph(graph: URIRef, *blocks: str, more: bool = False) -> str:
    body = "\n\n".join(blocks) + ("\n\n    …" if more else "")
    return f"{queries.shorten(graph)} {{\n{body}\n}}"


def example(title: str, name: str, more: bool = True) -> tuple[str, str, str]:
    subject, graph = named(name)
    return title, queries.shorten(graph), in_graph(graph, describe(subject, graph), more=more)


def vocab_block(iri: str) -> str:
    return re.search(rf"^{re.escape(iri)} a .*?\.\n", VOCAB, re.S | re.M).group(0).rstrip()


TOKENS = re.compile(
    r'(?P<s>"(?:[^"\\\n]|\\.)*"(?:@[A-Za-z-]+|\^\^[A-Za-z][\w-]*:[\w-]*)?)'
    r"|(?P<i><[^<>\s\"]*>)"
    r"|(?P<v>[?$][A-Za-z_]\w*)"
    r"|(?P<k>\b(?:SELECT|WHERE|GRAPH|OPTIONAL|BIND|AS|ORDER|GROUP_CONCAT|GROUP|BY|FILTER|NOT|EXISTS|CONCAT|STR|REPLACE|COALESCE)\b|(?<=\s)a(?=\s))"
    r"|(?P<p>[A-Za-z][\w-]*:(?:[\w.-]*[\w-])?)"
    r"|(?P<n>-?\b\d+(?:\.\d+)?\b)"
)


def highlight(src: str) -> str:
    out, last = [], 0
    for m in TOKENS.finditer(src):
        out.append(html.escape(src[last : m.start()], quote=False))
        out.append(f'<span class="t-{m.lastgroup}">{html.escape(m.group(0), quote=False)}</span>')
        last = m.end()
    out.append(html.escape(src[last:], quote=False))
    return "".join(out)


def details(name: str, where: str, src: str) -> str:
    return (
        f'      <details class="ex"><summary><span class="ex-name">{name}</span>'
        f'<code class="ex-where">{where}</code></summary>'
        f"<pre><code>{highlight(src)}</code></pre></details>\n"
    )


install, _ = named("BFE_D_31_TILT1_4")
bundle = URIRef(config.GRAPH + "09_FEAR/06_FEAR2/F2_INSTALLATION")
DATA_EXAMPLES = [
    ("Collection record", "gr:provenance",
     in_graph(URIRef(config.GRAPH + "provenance"), describe(bundle, URIRef(config.GRAPH + "provenance")), more=True)),
    example("Deployment", "BFE_D_31_TILT1_4"),
    example("Sensor", "TILT4"),
    example("Borehole", "BFE_D_31"),
    example("Borehole mouth survey", "BFE_D_31_STAKED_OUT_20240908"),
]

MAPPING_EXAMPLE = "\n".join(
    [MAPPING[0]] + [line for line in MAPPING if line.startswith("assignment,SENSOR_INSTAL,")
                    and line.split(",")[2] in ("BOREHOLE", "SENSOR", "SENSOR_COUPLING", "BOREHOLE_METER", "DEPLOYED_BY", "DEPLOYMENT_USER")]
)

VOCAB_EXAMPLES = [
    ("Clamped", "bedv:coupling", vocab_block("bedv:coupling-clamped")),
    ("Tilt meter", "bedv:sensor-type", vocab_block("bedv:sensor-type-tilt-meter")),
    ("Bedretto local grid", "bedv:crs", vocab_block("bedv:crs-bedretto-local-v1")),
]

QUERY_EXAMPLES = [
    ("hydromechanical-deployments", "Which hydromechanical sensors serve FEAR-2, and how were they installed?",
     "Data and the vocabulary's sensor-type hierarchy. The query asks for hydromechanical sensors and never names tilt meters."),
    ("describe-borehole", "What do we know about BFE_D_31?",
     "Data, ontology labels and vocabulary labels. Each property is named by its ontology label, and each concept value by its vocabulary label."),
    ("current-collar-position", "Where is the mouth of BFE_A_01 now?",
     "Its latest survey: BFE_A_01 was planned, then staked out two weeks later. Each survey keeps its own date and surveyor, so the history stays."),
]


def result_table(heads: list[str], cells: list[list[str]]) -> str:
    numeric = [all(re.fullmatch(r"-?\d+(\.\d+)?", row[i]) for row in cells) for i in range(len(heads))]
    th = "".join(f'<th{" class=\"num\"" if numeric[i] else ""}>{html.escape(h)}</th>' for i, h in enumerate(heads))
    trs = "".join(
        "<tr>" + "".join(f'<td{" class=\"num\"" if numeric[i] else ""}>{html.escape(c)}</td>' for i, c in enumerate(row)) + "</tr>"
        for row in cells
    )
    return f'<div class="result"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'


def questions_section() -> str:
    items = []
    for name, question, note in QUERY_EXAMPLES:
        sparql = queries.QUERIES[name][len(queries.PREFIXES):].strip("\n")
        heads, rows = queries.select(DS, name)
        assert rows, name
        items.append(
            f'      <details class="ex"><summary><span class="ex-name">{html.escape(question)}</span>'
            f'<code class="ex-where">just query {name}</code></summary>'
            f'<p class="ex-note">{html.escape(note)}</p>'
            f"<pre><code>{highlight(sparql)}</code></pre>"
            f'<div class="eyebrow">Result</div>{result_table(heads, rows)}</details>\n'
        )
    return (
        '  <section aria-labelledby="h-questions">\n'
        '    <h2 id="h-questions">Example questions</h2>\n'
        '    <div class="examples">\n' + "".join(items) + "    </div>\n  </section>\n\n"
    )


def section(caption: str, items, note: str = "") -> str:
    rows = "".join(details(*item) for item in items)
    note = f'      <p class="cap">{note}</p>\n' if note else ""
    return f'    <div class="examples">\n      <div class="eyebrow">{caption}</div>\n{rows}{note}    </div>\n'


page = PAGE.read_text()
page = re.sub(r'  <section aria-labelledby="h-questions">.*?\n  </section>\n\n', "", page, flags=re.S)
page = re.sub(r'    <div class="examples">.*?\n    </div>\n', "", page, flags=re.S)

sensor = DS.value(install, URIRef(config.NAMESPACES["ssn"] + "deployedSystem"))
thread = (
    "The examples follow one thread: tilt meter TILT4 is installed in borehole BFE_D_31, whose mouth was "
    "staked out on 8 September 2024. Each openBIS collection is a graph, and objects link across "
    f"collections by permId: the deployment names <code>{queries.shorten(sensor).replace(config.ID, 'bdr:')}</code>, "
    "and the tilt-meter collection describes that same IRI as TILT4. People's names are replaced in the fixture."
)
anchor = "    </figure>\n  </section>\n\n  <section aria-labelledby=\"h-model\">"
assert page.count(anchor) == 1
page = page.replace(anchor, "    </figure>\n" + section("From mapping/openbis-annotations.csv",
                    [("Fields of SENSOR_INSTAL", "openBIS field → term", MAPPING_EXAMPLE)],
                    "One row per openBIS type and field: the annotation it gets, the unit or concept scheme of "
                    "its values, and why a field is skipped.")
                    + "  </section>\n\n  <section aria-labelledby=\"h-model\">")

anchor = "    </figure>\n  </section>\n\n  <section aria-labelledby=\"h-vocab\">"
assert page.count(anchor) == 1
page = page.replace(anchor, "    </figure>\n" + section("Examples from the converted fixture", DATA_EXAMPLES, thread)
                    + "  </section>\n\n  <section aria-labelledby=\"h-vocab\">")

anchor = '    <p class="cap">Numbers'
i = page.index(anchor)
j = page.index("</p>\n", i) + len("</p>\n")
page = page[:j] + section("Examples from bedretto-vocab.ttl", VOCAB_EXAMPLES) + page[j:]

anchor = '  <section aria-labelledby="h-files">'
assert page.count(anchor) == 1
page = page.replace(anchor, questions_section() + anchor)

PAGE.write_text(page)
print("data examples:", len(DATA_EXAMPLES), "vocab examples:", len(VOCAB_EXAMPLES))
