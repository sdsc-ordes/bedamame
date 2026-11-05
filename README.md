# Bedamame

A design and a working prototype that make the data of the Bedretto
Underground Laboratory easier to find, understand, check and share.

The lab records its boreholes, sensors, sensor installations, rock cores and
logging runs in openBIS, its electronic lab notebook. Bedamame keeps openBIS as
it is and adds a layer of shared meaning on top. This repository is a starting
point: it explains the idea, shows that it works on the lab's real data, and
lists what a full project would still have to build.

## The problem

- People, boreholes and sensors are often typed as free text, so the same thing
  is spelled several ways and can't be searched reliably.
- Fields have no written definitions and aren't linked to any standard, so
  anyone outside the team has to guess what a value means.
- A question that spans several experiments or campaigns means exporting
  spreadsheets and joining them by hand.
- Nothing checks whether records contradict each other.

## The idea

The lab keeps entering data in openBIS, which stays the single source of truth.
Around it we add:

1. **A dictionary (ontology)** that defines every kind of thing the lab records
   and every field, reusing international standards where they fit (W3C
   SOSA/SSN for sensors, PROV-O for provenance, GeoSPARQL for locations, QUDT
   for units). Each openBIS field is labelled with its dictionary entry.
2. **Lists of allowed values (vocabularies)**, so each value is spelled one way
   and related values are grouped: a tilt meter counts as a hydromechanical
   sensor.
3. **A searchable copy of the data (knowledge graph)**, generated from openBIS
   automatically, which is checked against rules, queried across all
   experiments at once, and packaged for publication.

```
openBIS (the lab enters data, as today)
   │  automatic export
   ▼
searchable copy ──▶ checks: missing or contradictory values go back to the lab
                ──▶ questions across all experiments and campaigns
                ──▶ data packages for repositories and partners (RO-Crate)
```

## What it gives the lab

- **Find:** ask questions across all experiments, such as "Which
  hydromechanical sensors serve FEAR-2, and how were they installed?" or
  "Where is the mouth of borehole BFE_A_01 now, and who measured it?"
- **Understand:** every field and value has a definition, so the data makes
  sense to people outside the lab.
- **Trust:** automatic checks catch missing values and records that contradict
  each other.
- **Share:** datasets go out as RO-Crates, a standard package that repositories
  and other labs can read without knowing openBIS. This supports FAIR data.
- **Keep history:** a new survey of a borehole or a sensor's new position no
  longer overwrites the old one.

## What the prototype already shows

Run on exports of the lab's openBIS, the prototype:

- converts openBIS records into the searchable copy and answers example
  questions;
- found contradictions nobody had spotted, for example 75 borehole positions
  "staked out" after drilling had started, a sensor recorded at 14 m in a
  borehole listed as 12 m long, and a dip convention stated the opposite way
  to the values;
- found that openBIS's own RO-Crate export fails for 11 of the lab's 12 record
  types, and works around it;
- prepares six changes to openBIS (people and test beds as records instead of
  typed names, history for borehole and sensor positions, links between
  records, pick-lists instead of free text), each tested on a local copy of
  openBIS.

It builds on the ontology of the first
[Bedretto ontology project](https://github.com/sdsc-ordes/bedretto-ontology),
extended to cover everything the lab keeps in openBIS.

## What is still to do

- The code was written quickly, with AI assistance, to try ideas out. It is a
  proof of concept and should be rebuilt for production.
- The lab's openBIS administrator has to review and apply the six changes.
  None is applied yet.
- The prototype has seen only part of the data. It needs full exports of all
  12 record types.
- The dictionary needs a permanent web address and has to be published.
- Queries run on one computer. A shared graph database would let the whole lab
  use them.
- The licence for published data packages is not chosen yet.
- The lab still has to answer several questions about its data (see below).

## Where to find things

| For | Look at |
|---|---|
| The reasoning, in plain words | `docs/report.docx` |
| The whole design on one page, with diagrams and examples | `docs/architecture/index.html` (open it in a browser) |
| The six openBIS changes and why each is needed | `docs/architecture/changes.md` |
| Open questions and data issues for the lab | `docs/architecture/collaborator-requests.md` |
| The dictionary, vocabularies and rules | `src/ontology/bedretto/` |
| Which openBIS field means what | `src/mapping/openbis-annotations.csv` (opens as a spreadsheet) |

## Glossary

- **openBIS:** the electronic lab notebook and data store the lab uses, hosted
  by ETH Zurich.
- **Ontology:** a dictionary of the kinds of things a field works with and how
  they relate, written so that computers can use it.
- **Vocabulary (SKOS):** a list of allowed values, with definitions and
  groupings.
- **Shapes (SHACL):** rules the data must follow, such as required fields or
  allowed values, checked automatically.
- **Knowledge graph (RDF):** data stored as linked statements ("sensor TILT4 is
  installed in borehole BFE_D_31"), so data from many sources can be combined
  and queried together.
- **SPARQL:** the query language for knowledge graphs.
- **RO-Crate:** a standard way to package a dataset together with a description
  of what it contains.
- **FAIR:** Findable, Accessible, Interoperable, Reusable: the principles many
  funders ask research data to follow.

## Technical setup

<details>
<summary>How to run the prototype</summary>

### Run it

```bash
uv sync
just convert       # tests/fixtures/openbis-export.json → out/bedretto.trig, validate, run the queries
just test          # shapes, ontology, mapping, converter
just crate         # out/ro-crate-metadata.json, checked against the crate shapes and RO-Crate 1.2
just docs          # HTML documentation of the ontology and vocabularies in site/
just page-counts   # update the counts on docs/architecture/index.html
just               # list all recipes
```

`just convert` needs no openBIS: it converts the committed fixture, a dump of
the local openBIS with people's names replaced. With the local openBIS
(`tools/openbis/README.md`):

```bash
just openbis-up openbis-masterdata openbis-seed   # openBIS 7.0 with the lab's types and objects
just openbis-changes                              # rehearse the master-data changes 01-06
just openbis-annotate                             # annotate from src/mapping/ and check
just export                                       # dump → convert → validate → queries
```

### Pipeline

```
openBIS ── annotations: each object type and field names its ontology term
   │
   │  V3 API dump            src/bedamame/openbis_api.py --dump
   ▼
dump.json ── convert ──▶ out/bedretto.trig ── validate (SHACL) ──▶ query (SPARQL), crate
             src/bedamame/openbis_to_rdf.py, terms from src/mapping/openbis-annotations.csv
```

The converter reads a dump made through the openBIS V3 API, because openBIS
7.0's RO-Crate export fails on the lab's types. It writes one named graph per
openBIS collection, plus `gr:experiments` and `gr:provenance`. The queries run
in memory with rdflib; any SPARQL 1.1 store that reads TriG can take its place
if it also loads the ontology, vocabulary and shapes as the graphs
`gr:ontology`, `gr:vocab` and `gr:shapes`.

### Working with the openBIS administrator

Nothing here writes to the production openBIS; scripts refuse any host but
`local.openbis.ch`. The administrator sends a fresh master-data export, we
build each change from it and rehearse it locally, and they import
`out/openbis/changes/NN-name.xlsx` (with its note `NN-name.md`) using "Update
if exists". Review sheets with people's names stay in the git-ignored `out/`.

### Base IRI

Everything uses the placeholder `https://example.org/bedretto/`.
`just set-base URL` replaces it in the ontology, vocabulary, shapes, fixtures
and `src/bedamame/config.py`. Production annotations wait for the final URL,
because an openBIS import cannot change or remove an annotation once it is
there. The crate's profile IRI and licence in `src/bedamame/make_crate.py` are
placeholders too.

### Layout

| Path | Contents |
|---|---|
| `src/ontology/bedretto/` | Ontology, SKOS vocabulary and SHACL shapes |
| `src/ontology/crate/`, `src/ontology/skos/` | Shapes for the exported crate and for any SKOS vocabulary |
| `src/mapping/` | openBIS type and field → term; vocabulary term → concept; collection → experiment |
| `src/bedamame/` | Annotation, changes, dump, conversion, validation, queries, crate, page counts |
| `docs/` | The report; in `architecture/`, for the openBIS administrator: design page, proposed changes, requests |
| `tools/nix/` | Nix flake for the dev shell (direnv loads it) |
| `tools/openbis/` | The local openBIS 7.0, its seed and notes |
| `tests/fixtures/` | The openBIS dump and master-data export the tests use |

</details>
