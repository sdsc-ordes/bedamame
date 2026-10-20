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
    uv run scripts/validate.py

# Run the tests
test:
    uv run pytest -q

# Write HTML documentation of the ontology and vocabularies to site/ with pyLODE
docs:
    uv run scripts/docs.py

# Replace the base IRI (placeholder https://example.org/bedretto/) in ontology, data and fixtures
set-base URL:
    uv run scripts/set_base.py {{URL}}

# Validate with one survey's CRS removed; expects a violation
demo-failure:
    uv run scripts/validate.py --demo-failure

# List the example queries
list-queries:
    uv run scripts/queries.py --list

# Run one query by name, e.g. `just query current-collar-position`
query NAME:
    uv run scripts/queries.py --run {{NAME}}

# Run every query
queries:
    uv run scripts/queries.py --all

# Write out/ro-crate-metadata.json, validate it against the crate shapes, then check
# the REQUIRED rules of the RO-Crate 1.2 base profile
crate:
    uv run scripts/make_crate.py
    uv run rocrate-validator -y --disable-color validate -p ro-crate-1.2 out/

# Report the RECOMMENDED rules of the RO-Crate 1.2 base profile too; informational
crate-lint: crate
    -uv run rocrate-validator -y --disable-color validate -p ro-crate-1.2 -l recommended -v --no-paging out/

# Convert the committed openBIS dump to out/bedretto.trig, validate it and run the queries; needs no Docker
convert:
    uv run scripts/openbis_to_rdf.py
    uv run scripts/validate.py
    uv run scripts/queries.py --all

# Dump the local openBIS, convert, validate and run the queries
export:
    uv run scripts/openbis_api.py --dump out/openbis/dump.json
    uv run scripts/openbis_to_rdf.py --export out/openbis/dump.json
    uv run scripts/validate.py
    uv run scripts/queries.py --all

# Convert, validate, run the queries, build the crate
all: convert crate

# Start the local openBIS 7.0.0 at https://local.openbis.ch; the first start takes a few minutes
openbis-up:
    test -f openbis/.env || cp openbis/.env.example openbis/.env
    docker compose -f openbis/compose.yaml up -d --wait --wait-timeout 900
    curl -fsSk https://local.openbis.ch/openbis/webapp/eln-lims/version.txt

# Import the lab's 12 object types, cleaned for 7.0, into the local openBIS
openbis-masterdata:
    uv run scripts/openbis_workbook.py "{{lab}}/all-object-types.2026-09-23/object-types.xlsx" --import

# Import boreholes, sensors, installations and stubs into the local openBIS
openbis-seed:
    uv run openbis/seed.py --import

# Rehearse the master-data changes 01-06 on the local openBIS: for each, a fresh export, generate, import
openbis-changes:
    uv run scripts/openbis_changes.py --local

# Write tests/fixtures/openbis-export.json from the local openBIS, with people's names replaced
openbis-fixture:
    uv run scripts/openbis_api.py --dump tests/fixtures/openbis-export.json --anonymise --select {{fixture}}

# Annotate the local openBIS from mapping/: fresh master-data export, annotate, import, check
openbis-annotate:
    uv run scripts/openbis_api.py --masterdata out/openbis/export
    uv run scripts/annotate_masterdata.py out/openbis/export/object-types.xlsx --import
    uv run scripts/annotate_masterdata.py --check

# Stop the local openBIS and keep its data
openbis-down:
    docker compose -f openbis/compose.yaml down

# Follow the local openBIS logs
openbis-logs:
    docker compose -f openbis/compose.yaml logs -f

# Stop the local openBIS and delete its data
openbis-reset:
    docker compose -f openbis/compose.yaml down -v

# Remove generated files
clean:
    rm -rf out
