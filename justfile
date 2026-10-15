# List the available recipes
default:
    @just --list

# Install the Python dependencies into .venv
sync:
    uv sync

# Validate the data against the Bedretto shapes and the vocabulary against the SKOS shapes
validate:
    uv run scripts/validate.py

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

# Validate, run the queries, build the crate
all: validate queries crate

# Remove generated files
clean:
    rm -rf out
