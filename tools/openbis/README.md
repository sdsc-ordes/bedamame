# Local openBIS 7.0.0

A local copy of openBIS for rehearsing master-data changes before the collaborator applies them in production. Nothing in this repository writes to production: scripts refuse any host other than `local.openbis.ch` (`LOCAL_HOSTS` in `src/bedamame/openbis_api.py`).

## Start

```sh
just openbis-up            # https://local.openbis.ch, first start takes a few minutes
just openbis-masterdata    # the lab's 12 object types, cleaned for 7.0
just openbis-seed          # boreholes, sensors, installations, stubs
just openbis-changes       # rehearse the master-data changes 01-06
just openbis-annotate      # annotate from src/mapping/ and check
just openbis-reset         # drop everything (volumes included)
```

`local.openbis.ch` resolves to 127.0.0.1 and the ingress certificate is valid for it. Credentials are local-only and live in `tools/openbis/.env` (copied from `.env.example` on first start; direnv loads it). Log in to the ELN as `admin` with `OPENBIS_PASSWORD`.

## What differs from the 7.x Docker quickstart

`as/openbis.conf` adds `-Das.code-plugins.allowed-editing-users=system,admin`. 7.0 lets only `system` import validation scripts; the lab's CORES type has one.

`openbis-local` only publishes `latest`, so it is pinned by digest.

## Importing master data the way the collaborator will

`uv run src/bedamame/openbis_workbook.py EXPORT` writes `out/openbis/masterdata-import/` and a zip of it: `masterdata.xlsx` plus the `scripts/` folder its validation scripts come from.

In the admin UI: **Tools → Import → All**, drop the zip, **Mode: Update if exists**, **Import**. `--import` (what `just openbis-masterdata` runs) does the same through the API: upload to the session workspace, then `executeImport`.

To import into 7.0, the lab's 2026-09-23 export needed these changes, which the script makes:

- Only the 12 Bedretto sample types and the 18 non-`$` vocabularies they use; 7.0 ships the ELN defaults and `$` vocabularies.
- Export-only columns dropped (Registrator, Registration Date, Modification Date), and `Unique Subcodes`, which 7.0 rejects (all FALSE in the export).
- `$NAME`, `$DOCUMENT`, `$XMLCOMMENTS`, `$BARCODE` are `NAME`, `DOCUMENT`, `XMLCOMMENTS`, `BARCODE` in 7.0 and must be flagged `Internal`; otherwise the import tries to update them, which only `system` may do. `PRODUCT.DESCRIPTION` is internal in 7.0 too.
- The lab also has its own plain `NAME` (BOREHOLE_LOGGING, label "Filename"). In 7.0 it is the same property as the internal `NAME`, so it takes that definition and the label "Filename" is lost.

Observed while importing:

- `START_DATE` and `END_DATE` are DATE in the lab's export and TIMESTAMP in 7.0. The import keeps TIMESTAMP **without an error**: an Excel import never changes an existing data type.
- 7.0's own Excel export has `Internal`, `Multivalued`, `Unique`, `Pattern`, `Internal Assignment` columns, and its property rows carry the **assignment's** annotation in the three ontology columns (NAME is `schema:name` on PERSON, blank on ORGANIZATION).

## Annotations

`just openbis-annotate` does what the collaborator will do in production: a fresh master-data export of the Bedretto types, including those changes 01–06 add (`src/bedamame/openbis_api.py --masterdata`), annotated from `src/mapping/openbis-annotations.csv` (`src/bedamame/annotate_masterdata.py`), imported with "Update if exists", then checked against the mapping (`--check`, read-only). `out/openbis/annotated/` holds the zip to import and `annotations-changes.md`, the note for the collaborator.

What the 7.0 import does with the three ontology columns (tested locally):

- On a type row they annotate the type; on a property row they annotate the **assignment**, even for a property only one type uses. The Excel import never annotates a property type, so the mapping has type and assignment rows only.
- It fills the `predicate*` fields (Ontology Id, Version, Annotation Id), as the admin UI form and 7.0's own annotations do; `descriptor*` stay empty.
- It only adds. Importing the same annotation again changes nothing; a different version or term adds a second annotation next to the first; clearing the cells removes nothing. The export lists every annotation of an item, one per line, so the generator reports unwanted ones for removal by hand in the admin UI.
- It cannot annotate any field of the built-in PERSON and ORGANIZATION types, not even one a change added: admin gets "Internal property assignments can be managed only by the system user". V3 `createSemanticAnnotations` works as admin, so the note lists those annotations for the collaborator to add in the admin UI, and `--import` creates them through V3 locally.
- A validation script `X.py` becomes plugin `TYPE.X`, and the export writes `TYPE.X.py`, so re-importing an export unchanged adds a plugin `TYPE.TYPE.X` each time. The generator drops one `TYPE.` prefix so the existing plugin is kept.

Ontology Id and Version per prefix are in `src/bedamame/config.py` (`ANNOTATION_SOURCES`). The generator counts an annotation with the same term IRI as present, whatever its Ontology Id and Version, and leaves it as it is: 7.0's own PERSON annotations use `https://schema.org` without the slash. So a new ontology version adds no second annotation, but annotations keep the version they were made with. Decide before the first production import whether the version should be part of the annotation.

## Seed

`seed.py` writes `out/openbis/seed.xlsx` (object import format: SPACE, PROJECT, EXPERIMENT and SAMPLE sections) from:

- `drive-files/CSV/borehole_information.csv`: 111 boreholes, borehole name as code so `/INFRASTRUCTURE/BOREHOLES/BFE_D_42` resolves; the current mouth position from `borehole_mouth_coord.csv` (via `coord_id`), coordinate system `global-local`; `TM` stripped for the REAL `LOCATION_TM`.
- The four object exports. Their headers are labels ("Remarks" for NOTES, "Filename" for NAME), but the property columns follow the type's assignments in order, so they are mapped by position. `DOCUMENT`, `XMLCOMMENTS` and `GENERAL_PROTOCOL.SPREADSHEET` are blanked; only the WELLTEC parent is dropped.
- Stubs for what the exports reference but do not contain: SEIS_SENSOR GS100-600-01/02 (serials from the installs), DEVICE DEV8–DEV11 (the tilt meters' computers), SENSORS LY1066.

The collection for boreholes is a stand-in, `/INFRASTRUCTURE/BOREHOLES/BOREHOLES`, until the collaborator gives the real one. The importer accepts vocabulary labels and stores term codes ("Sanded" becomes `SANDED-IN`).

## Master-data changes

`just openbis-changes` rehearses the six changes in order. For each, it exports the master data of the Bedretto types and their objects, builds the change from that export, and imports it with "Update if exists". `out/openbis/changes/` then holds the file to import (`NN-name.xlsx`, or a zip when it carries validation scripts) and `NN-name.md`, the note for the collaborator. `out/openbis/review/` holds the review sheets, which contain names.

For production, the collaborator's exports go in instead: `uv run src/bedamame/openbis_changes.py 01 --masterdata DIR/object-types.xlsx --objects OBJECTS.xlsx`. `--annotate` also fills the ontology columns of new types and fields; leave it out until the final domain is set.

What each change does, for the collaborator: [docs/architecture/changes.md](../../docs/architecture/changes.md).

New fields get new codes; the old fields stay until the collaborator retires them. New vocabulary terms are added to `src/mapping/openbis-terms.csv`.

What the 7.0 import does (tested locally):

- An import is all or nothing: one bad value and nothing is imported.
- A type section may list only the new property rows; existing assignments are kept. The built-in PERSON accepts new assignments.
- Listing only the new terms of an existing vocabulary adds them.
- An object update changes only the columns in the sheet, and empty cells change nothing.
- Multi-valued object links take identifiers separated by newlines. Multi-valued vocabulary fields take term codes separated by **commas**; with newlines the whole value is read as one code.
- A type row copied from an export names its validation script, so the change has to carry that script (`05-object-links` is a zip because of CORES). A new script `X.py` becomes plugin `TYPE.X`; the old plugin stays.
- Object exports write vocabulary values as labels and booleans as `true`/`false`.

## API

`src/bedamame/openbis_api.py` is a small V3 JSON-RPC client; `uv run src/bedamame/openbis_api.py` logs in and lists the spaces.

- pyBIS 1.37.5 cannot search 7.0.0: the server rejects a JSON object whose only key is `@type`, which pyBIS sends for empty criteria and fetch options. The client gives every typed object an `@id`.
- Responses send an object once, then refer to it by its `@id`; the client puts the objects back.
- Searching collections by space fails server-side (`column t0.space_id does not exist`); search all and filter.
- V3 returns DATE values as `yyyy-MM-dd` and TIMESTAMPs as `yyyy-MM-dd HH:mm:ss Z`; a year alone is rejected.
- Object properties come back by code: links as permIds (a list when multi-valued), vocabulary values as term codes, booleans as `true`/`false`. Registration and modification dates are milliseconds since 1970.

`uv run src/bedamame/openbis_api.py --dump FILE` writes what the converter (`src/bedamame/openbis_to_rdf.py`) reads: every object of the Bedretto types with its properties, registrator, modifier and dates; the types' data types and annotations; the collections' names. `--select IDENTIFIER...` keeps only those collections and objects, what they link to, and the surveys and sensor positions that describe them. `--anonymise` drops the fields without an annotation (the free-text names among them) and replaces people's and users' names. `just openbis-fixture` uses both to write `tests/fixtures/openbis-export.json`.

## RO-Crate export

openBIS 7.0.0's own RO-Crate export fails for 11 of the 12 Bedretto types: on any DATE value, on the property labels "Project" and "Experiment", and on multi-line text without widget metadata. The converter therefore reads a V3 dump.
