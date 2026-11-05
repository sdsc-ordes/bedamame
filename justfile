# The lab's openBIS export (git-ignored)
lab := "drive-files/openBIS-20261006T123341Z-1-001/openBIS"
# What tests/fixtures/openbis-export.json holds, with what these link to and the surveys of their boreholes
fixture := "/09_FEAR/06_FEAR2/F2_INSTALLATION /09_FEAR/06_FEAR2/F2_INSTALLATION_SEIS /EQUIPMENT/SENSOR_CATALOG/TILTMETERS /REGISTERS/TESTBEDS/TESTBEDS_COLLECTION /INFRASTRUCTURE/BOREHOLES/BFE_A_01"

# List the available recipes
default:
    @just --list

# Install the Python dependencies into .venv
sync:
    uv sync

# Validate out/bedretto.trig against the Bedretto shapes and the vocabulary against the SKOS shapes
validate:
    uv run src/bedamame/validate.py

# Run the tests
test:
    uv run pytest -q

# Write HTML documentation of the ontology and vocabularies to site/ with pyLODE
docs:
    uv run src/bedamame/docs.py

# Update the counts on docs/architecture/index.html from the ontology, vocabulary, mapping and changes
page-counts:
    uv run src/bedamame/page_counts.py

# Replace the base IRI (placeholder https://example.org/bedretto/) in ontology, data and fixtures
set-base URL:
    uv run src/bedamame/set_base.py {{URL}}

# List the example queries
list-queries:
    uv run src/bedamame/queries.py --list

# Run one query by name, e.g. `just query current-collar-position`
query NAME:
    uv run src/bedamame/queries.py --run {{NAME}}

# Run every query
queries:
    uv run src/bedamame/queries.py --all

# Write out/ro-crate-metadata.json, validate it against the crate shapes, then check
# the REQUIRED rules of the RO-Crate 1.2 base profile
crate:
    uv run src/bedamame/make_crate.py
    uv run rocrate-validator -y --disable-color validate -p ro-crate-1.2 out/

# Convert the committed openBIS dump to out/bedretto.trig, validate it and run the queries; needs no Docker
convert:
    uv run src/bedamame/openbis_to_rdf.py
    uv run src/bedamame/validate.py
    uv run src/bedamame/queries.py --all

# Dump the local openBIS, convert, validate and run the queries
export:
    uv run src/bedamame/openbis_api.py --dump out/openbis/dump.json
    uv run src/bedamame/openbis_to_rdf.py --export out/openbis/dump.json
    uv run src/bedamame/validate.py
    uv run src/bedamame/queries.py --all

# Convert, validate, run the queries, build the crate
all: convert crate

# Start the local openBIS 7.0.0 at https://local.openbis.ch; the first start takes a few minutes
openbis-up:
    test -f tools/openbis/.env || cp tools/openbis/.env.example tools/openbis/.env
    docker compose -f tools/openbis/compose.yaml up -d --wait --wait-timeout 900
    curl -fsSk https://local.openbis.ch/openbis/webapp/eln-lims/version.txt

# Import the lab's 12 object types, cleaned for 7.0, into the local openBIS
openbis-masterdata:
    uv run src/bedamame/openbis_workbook.py "{{lab}}/all-object-types.2026-09-23/object-types.xlsx" --import

# Import boreholes, sensors, installations and stubs into the local openBIS
openbis-seed:
    uv run tools/openbis/seed.py --import

# Rehearse the master-data changes 01-06 on the local openBIS: for each, a fresh export, generate, import
openbis-changes:
    uv run src/bedamame/openbis_changes.py --local

# Write tests/fixtures/openbis-export.json from the local openBIS, with people's names replaced
openbis-fixture:
    uv run src/bedamame/openbis_api.py --dump tests/fixtures/openbis-export.json --anonymise --select {{fixture}}

# Annotate the local openBIS from src/mapping/: fresh master-data export, annotate, import, check
openbis-annotate:
    uv run src/bedamame/openbis_api.py --masterdata out/openbis/export
    uv run src/bedamame/annotate_masterdata.py out/openbis/export/object-types.xlsx --import
    uv run src/bedamame/annotate_masterdata.py --check

# Stop the local openBIS and keep its data
openbis-down:
    docker compose -f tools/openbis/compose.yaml down

# Follow the local openBIS logs
openbis-logs:
    docker compose -f tools/openbis/compose.yaml logs -f

# Stop the local openBIS and delete its data
openbis-reset:
    docker compose -f tools/openbis/compose.yaml down -v

# Remove generated files
clean:
    rm -rf out
