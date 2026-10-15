import html
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
PAGE = Path(sys.argv[2])

TRIG = (ROOT / "data" / "bedretto.trig").read_text()
VOCAB = (ROOT / "ontology" / "bedretto" / "bedretto-vocab.ttl").read_text()


def graph_blocks(name: str) -> list[str]:
    body = re.search(rf"^{re.escape(name)} {{\n(.*?)^}}", TRIG, re.S | re.M).group(1)
    return [b for b in body.strip("\n").split("\n\n") if b.strip()]


def pick(name: str, needle: str) -> str:
    blocks = [b for b in graph_blocks(name) if needle in b]
    assert len(blocks) == 1, (name, needle)
    return blocks[0]


def in_graph(name: str, *blocks: str, more: bool = False) -> str:
    body = "\n\n".join(blocks) + ("\n\n    …" if more else "")
    return f"{name} {{\n{body}\n}}"


def vocab_block(iri: str) -> str:
    return re.search(rf"^{re.escape(iri)} a .*?\.\n", VOCAB, re.S | re.M).group(0).rstrip()


TOKENS = re.compile(
    r'(?P<s>"(?:[^"\\\n]|\\.)*"(?:@[A-Za-z-]+|\^\^[A-Za-z][\w-]*:[\w-]*)?)'
    r"|(?P<i><[^<>\s\"]*>)"
    r"|(?P<v>[?$][A-Za-z_]\w*)"
    r"|(?P<k>\b(?:SELECT|WHERE|GRAPH|OPTIONAL|BIND|AS|ORDER|BY|CONCAT|STR|REPLACE|COALESCE)\b|(?<=\s)a(?=\s))"
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


DATA_EXAMPLES = [
    ("Assertion graph", "gr:provenance",
     in_graph("gr:provenance", pick("gr:provenance", "gr:campaign-fear2-install"), more=True)),
    ("Borehole", "gr:register-boreholes",
     in_graph("gr:register-boreholes", pick("gr:register-boreholes", '"BFE_D_31"'), more=True)),
    ("Collar survey", "gr:survey-flotron-2024-09-08",
     in_graph("gr:survey-flotron-2024-09-08", *graph_blocks("gr:survey-flotron-2024-09-08"))),
    ("Sensor", "gr:register-sensors",
     in_graph("gr:register-sensors", pick("gr:register-sensors", '"tilt01"'), more=True)),
    ("Deployment", "gr:campaign-fear2-install",
     in_graph("gr:campaign-fear2-install",
              pick("gr:campaign-fear2-install", "a bed:Experiment"),
              pick("gr:campaign-fear2-install", '"tilt01 in BFE_D_31"'), more=True)),
]

VOCAB_EXAMPLES = [
    ("Clamped", "bedv:coupling", vocab_block("bedv:coupling-clamped")),
    ("Tilt meter", "bedv:sensor-type", vocab_block("bedv:sensor-type-tilt-meter")),
    ("Bedretto tunnel local grid v1", "bedv:crs", vocab_block("bedv:crs-bedretto-local-v1")),
]


sys.path.insert(0, str(ROOT / "scripts"))
import queries  # noqa: E402

QUERY_EXAMPLES = [
    ("hydromechanical-deployments", "Which hydromechanical sensors serve FEAR-2, and how were they installed?",
     "Data and the vocabulary's sensor-type hierarchy. The query asks for hydromechanical sensors and never names tilt meters."),
    ("describe-borehole", "What do we know about BFE_D_31?",
     "Data, ontology labels and vocabulary labels. Each property is named by its ontology label, and each concept value by its vocabulary label."),
]


def result_table(rows) -> str:
    heads = [str(v) for v in rows[0].labels]
    cells = [["" if r[h] is None else str(r[h]) for h in heads] for r in rows]
    numeric = [all(re.fullmatch(r"-?\d+(\.\d+)?", row[i]) for row in cells) for i in range(len(heads))]
    th = "".join(f'<th{" class=\"num\"" if numeric[i] else ""}>{html.escape(h)}</th>' for i, h in enumerate(heads))
    trs = "".join(
        "<tr>" + "".join(f'<td{" class=\"num\"" if numeric[i] else ""}>{html.escape(c)}</td>' for i, c in enumerate(row)) + "</tr>"
        for row in cells
    )
    return f'<div class="result"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'


def questions_section() -> str:
    ds = queries.load()
    items = []
    for name, question, note in QUERY_EXAMPLES:
        sparql = queries.QUERIES[name][len(queries.PREFIXES):].strip("\n")
        rows = list(ds.query(queries.QUERIES[name]))
        assert rows, name
        items.append(
            f'      <details class="ex"><summary><span class="ex-name">{html.escape(question)}</span>'
            f'<code class="ex-where">just query {name}</code></summary>'
            f'<p class="ex-note">{html.escape(note)}</p>'
            f"<pre><code>{highlight(sparql)}</code></pre>"
            f'<div class="eyebrow">Result</div>{result_table(rows)}</details>\n'
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

anchor = "    </figure>\n  </section>\n\n  <section aria-labelledby=\"h-vocab\">"
assert page.count(anchor) == 1
page = page.replace(anchor, "    </figure>\n" + section("Examples from data/bedretto.trig", DATA_EXAMPLES,
                    "The examples follow one thread: tilt01 is deployed in BFE_D_31, whose collar Flotron "
                    "surveyed on 8 September 2024. Graphs link by sharing IRIs: the deployment names "
                    "<code>bdr:6elykqev…</code>, and the sensor register describes that same IRI as tilt01.")
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
