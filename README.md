# bedamame

The semantic layer for the Bedretto Underground Laboratory's openBIS. openBIS is
where the lab records boreholes, sensors, installations, cores and logging runs.
This repository holds the ontology, vocabulary and shapes that say what those
records mean. It also prepares the openBIS changes that make the records fit
them, and converts openBIS exports to RDF named graphs. The RDF is validated
with SHACL, queried with SPARQL and packaged as an RO-Crate.

## How it fits together

```
openBIS ── annotations: each object type and field names its ontology term
   │
   │  V3 API dump            scripts/openbis_api.py --dump
   ▼
dump.json ── convert ──▶ out/bedretto.trig ── validate (SHACL) ──▶ query (SPARQL), crate
             scripts/openbis_to_rdf.py, terms from mapping/openbis-annotations.csv
```

1. **Annotations.** Every Bedretto object type and field in openBIS carries a
   semantic annotation (Ontology Id, Version, Annotation Id) that names a term:
   a standard one where it means the same, such as `schema:name` or
   `sosa:Sensor`, otherwise a `bed:` term aligned to the nearest standard.
   `mapping/openbis-annotations.csv` is the source; `annotate_masterdata.py`
   writes it into a master-data export for import.
2. **Master-data changes.** Seven changes make the openBIS records fit the
   ontology: people, organisations and test beds as objects; borehole mouth
   surveys and sensor positions with their history; links instead of names
   typed as text; vocabularies instead of free text
   (`scripts/openbis_changes.py`, see `openbis/README.md`).
3. **Export and conversion.** The converter reads a dump made through the
   openBIS V3 API (openBIS 7.0's RO-Crate export fails on the lab's types).
   It takes each field's term from the mapping, turns vocabulary terms into
   SKOS concepts and numbers with units into QUDT quantity values, and writes
   one named graph per openBIS collection.
4. **Validation and queries** run on that RDF, with the ontology, vocabulary
   and shapes alongside.

## Usage

```bash
uv sync
just convert       # tests/fixtures/openbis-export.json → out/bedretto.trig, validate, run the queries
just test          # shapes, ontology, mapping, converter
just crate         # out/ro-crate-metadata.json, checked against the crate shapes and RO-Crate 1.2
just docs          # HTML documentation of the ontology and vocabularies in site/
```

`just convert` needs no openBIS: it converts the committed fixture, a dump of
the local openBIS with people's names replaced. With the local openBIS
(`openbis/README.md`):

```bash
just openbis-up openbis-masterdata openbis-seed   # openBIS 7.0 with the lab's types and objects
just openbis-changes                              # rehearse the master-data changes 01-07
just openbis-annotate                             # annotate from mapping/ and check
just export                                       # dump → convert → validate → queries
just load                                         # SPARQL endpoint at http://localhost:7878
```

`uv run scripts/queries.py --endpoint --all` runs the queries against the
endpoint instead of in memory; Oxigraph writes numbers and times in canonical
form (`19` for `19.0`), otherwise the results are the same.

## Working with the openBIS administrator

Nothing here writes to the production openBIS; scripts refuse any host but
`local.openbis.ch`. A collaborator reviews and applies every change:

1. They send a fresh master-data export (and, for changes that move data, an
   export of the objects).
2. We build the change from it, rehearse it on the local openBIS, and send
   `out/openbis/changes/NN-name.xlsx` (or `.zip`) with `NN-name.md`, a note in
   plain language. Changes that create people come with a review sheet of the
   names as written, which stays in the git-ignored `out/`.
3. They import it in the admin UI with "Update if exists".

Annotations go the same way: `annotated.zip` and `annotations-changes.md`.
openBIS will not let an import annotate its built-in PERSON and ORGANIZATION
fields, so the note lists those few for the collaborator to add by hand. What
we need from them is in `openbis/collaborator-requests.md`.

## Base IRI

Everything Bedretto publishes lives under one base IRI, still the placeholder
`https://example.org/bedretto/`. `just set-base URL` replaces it in the
ontology, vocabulary, shapes, fixtures and `scripts/config.py`, which the
scripts take their namespaces from. Production annotations wait for the final
URL, because an import cannot change or remove an annotation once it is there.

## Layout

| Path | Contents |
|---|---|
| `ontology/bedretto/bedretto-ontology.ttl` | Classes and properties |
| `ontology/bedretto/bedretto-vocab.ttl` | SKOS concept schemes for controlled values |
| `ontology/bedretto/bedretto-shapes.ttl` | SHACL shapes for the converted data |
| `ontology/crate/crate-shapes.ttl` | SHACL shapes for the exported crate |
| `ontology/skos/skos-shapes.ttl` | SHACL shapes for any SKOS vocabulary |
| `mapping/openbis-annotations.csv` | openBIS type and field → term, unit, scheme |
| `mapping/openbis-terms.csv` | openBIS vocabulary term → SKOS concept |
| `mapping/collections.csv` | openBIS project or collection → experiment, campaign |
| `openbis/` | The local openBIS 7.0, its seed, notes and requests for the collaborator |
| `scripts/` | Annotation, changes, dump, conversion, validation, queries, crate |
| `endpoint/` | A local Oxigraph SPARQL endpoint |
| `tests/fixtures/` | The openBIS dump and master-data export the tests use; `handwritten.trig`, the hand-written prototype data, for the shape tests |

## Ontology

The definitions and coverage follow the
[Bedretto ontology](https://github.com/sdsc-ordes/bedretto-ontology), which
combines classes and shapes in one file and lists controlled values as strings.
Here they are split three ways:

- The ontology defines what each class and property means. It aligns to SOSA/SSN,
  PROV-O, GeoSPARQL, OWL-Time and QUDT where they fit, for example a core is a
  `sosa:Sample`.
- The vocabulary holds every controlled value as a SKOS concept. Hidden labels
  record the spellings found in the lab's exports, e.g. `Campled` for
  `Clamped`. openBIS vocabulary terms map to concepts through
  `mapping/openbis-terms.csv`.
- The shapes say which properties each class takes and how often. A property
  with a controlled value must point to a concept in a named scheme, so a new
  value is added to the vocabulary only.

The SKOS shapes check the vocabulary itself: labels, schemes and hierarchy.
Nothing in them is specific to Bedretto, so they sit apart from the Bedretto
files, as the crate shapes do.

## Graphs

| Graph | Holds |
|---|---|
| `gr:<space>/<project>/<collection>` | The objects of one openBIS collection, e.g. `gr:09_FEAR/06_FEAR2/F2_INSTALLATION` |
| `gr:experiments` | Experiments, from `mapping/collections.csv`; openBIS has no experiment object |
| `gr:provenance` | One record per collection graph, and the openBIS users |

Every object is `bdr:<permId>`, so links between collections are shared IRIs.
openBIS users are `bdr:user/<userId>`. The default graph is empty. Collection
paths differ between instances, so queries find records by class
(`GRAPH ?g { ?b a bed:Borehole }`) rather than by graph name. `queries.py`
loads the ontology, vocabulary and shapes as graphs of their own, `gr:ontology`,
`gr:vocab` and `gr:shapes`, so queries can join records with labels, concept
hierarchies and constraints.

## Provenance

Each collection graph is described once, in `gr:provenance`, as a `prov:Bundle`:

| Property | Meaning | Required |
|---|---|---|
| `schema:name` | The campaign from `mapping/collections.csv`, or the collection's name | no |
| `prov:generatedAtTime` | When an object in it was last modified | exactly one |
| `prov:wasAttributedTo` | The openBIS users who registered its objects | at least one |

A collection can hold many surveys, so a survey carries its own date
(`bed:surveyDate`) and surveyors (`bed:surveyedBy`); openBIS keeps the history
of every value.

The crate's profile IRI and licence in `scripts/make_crate.py` are placeholders.
