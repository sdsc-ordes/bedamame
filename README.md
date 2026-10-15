# bedamame

An example metadata store for the Bedretto Underground Laboratory. Data is held
in RDF named graphs, one per survey, plan, installation campaign or register that
asserted it, validated with SHACL over the union of all graphs, and exported as an
RO-Crate.

## Usage

```bash
uv sync
uv run scripts/validate.py                  # Bedretto shapes over all graphs, SKOS shapes over the vocabulary
uv run scripts/validate.py --demo-failure   # remove one survey's CRS, expect a violation
uv run scripts/queries.py --all             # example SPARQL queries
uv run scripts/make_crate.py                # write and validate out/ro-crate-metadata.json
uv run pytest                               # shape, vocabulary and ontology tests
```

`just docs` writes HTML documentation of the ontology and each vocabulary to
`site/` with pyLODE. `just set-base URL` replaces the placeholder base IRI
`https://example.org/bedretto/` in the ontology, data and test fixtures, and in
`scripts/config.py`, which the scripts take their namespaces from.

`just all` runs validation, the queries and the crate build in order. `just crate`
also checks the crate against the REQUIRED rules of the RO-Crate 1.2 base profile
with [rocrate-validator](https://github.com/crs4/rocrate-validator); `just crate-lint`
reports its RECOMMENDED rules as well, without failing.

## Layout

| Path | Contents |
|---|---|
| `ontology/bedretto/bedretto-ontology.ttl` | Classes and properties |
| `ontology/bedretto/bedretto-vocab.ttl` | SKOS concept schemes for controlled values |
| `ontology/bedretto/bedretto-shapes.ttl` | SHACL shapes for the store |
| `ontology/crate/crate-shapes.ttl` | SHACL shapes for the exported crate |
| `ontology/skos/skos-shapes.ttl` | SHACL shapes for any SKOS vocabulary |
| `data/bedretto.trig` | Instance data |
| `scripts/` | `validate.py`, `queries.py`, `make_crate.py` |

## Ontology

The definitions and coverage follow the
[Bedretto ontology](https://github.com/sdsc-ordes/bedretto-ontology), which
combines classes and shapes in one file and lists controlled values as strings.
Here they are split three ways:

- The ontology defines what each class and property means. It aligns to SOSA/SSN,
  PROV-O, GeoSPARQL, OWL-Time and QUDT where they fit, for example a core is a
  `sosa:Sample`.
- The vocabulary holds every controlled value as a SKOS concept. Hidden labels
  record the spellings found in the spreadsheet exports, e.g. `Campled` for
  `Clamped`.
- The shapes say which properties each class takes and how often. A property
  with a controlled value must point to a concept in a named scheme, so a new
  value is added to the vocabulary only.

The SKOS shapes check the vocabulary itself: labels, schemes and hierarchy.
Nothing in them is specific to Bedretto, so they sit apart from the Bedretto
files, as the crate shapes do.

## Graphs

| Graph | Holds |
|---|---|
| `gr:register-boreholes`, `gr:register-sensors`, `gr:register-testbeds`, `gr:register-agents` | The lab's lists of boreholes, sensors, test beds and people |
| `gr:survey-…`, `gr:campaign-…` | What one survey, plan or installation campaign asserted |
| `gr:provenance` | One record per survey, plan or campaign graph |

The default graph is empty. Every query pattern names the graph it reads, so
the queries give the same results on any SPARQL store. Controlled values, the
coordinate system included, are vocabulary terms rather than data. `queries.py`
loads the ontology, vocabulary and shapes as graphs of their own, `gr:ontology`,
`gr:vocab` and `gr:shapes`, so queries can join records with labels, concept
hierarchies and constraints.

## Provenance

Each survey, plan or campaign graph is described once, in `gr:provenance`, as a
`prov:Bundle`:

| Property | Meaning | Required |
|---|---|---|
| `schema:name` | What the graph holds | no |
| `prov:generatedAtTime` | When the record was made | exactly one |
| `prov:wasAttributedTo` | Who is responsible for the record | at least one |
| `dcterms:contributor` | Who took part in the fieldwork, when that differs | no |
| `dcterms:temporal` | When the fieldwork happened, as a `time:Interval`, when that differs | at most one |

There is no separate activity for the survey or campaign: the graph record carries
its name, dates and people. The register graphs have no record yet.

## Data

Values in `data/bedretto.trig` come from the BedrettoLab spreadsheet exports in
`drive-files/`, which is git-ignored. These parts do not:

- Entity IRIs: UUIDs under the placeholder base `https://example.org/bedretto/`.
- The coordinate reference system: a placeholder concept in the vocabulary, since
  the exports record none.
- The names of surveys, deployments and graphs, which are composed from source
  values.

The crate's profile IRI and licence in `scripts/make_crate.py` are placeholders
too.
