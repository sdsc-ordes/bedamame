import argparse
import re
import sys
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parents[2]
# every file that spells out the base, in prefixes and in literals (sh:namespace, STRSTARTS, WKT)
FOLDERS = ["src/ontology", "tests/fixtures"]
SUFFIXES = {".ttl", ".trig", ".json", ".jsonld"}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Replace the base IRI of the ontology, vocabulary, shapes and data"
    )
    ap.add_argument("base", help="new base IRI, ending in /")
    args = ap.parse_args()

    new = args.base
    if not re.fullmatch(r"https?://[^\s<>\"]+/", new):
        print(f"not an http(s) IRI ending in /: {new}", file=sys.stderr)
        return 2
    old = config.BASE
    if new == old:
        print(f"base is already {old}")
        return 0

    files = [
        p
        for f in FOLDERS
        for p in sorted((ROOT / f).rglob("*"))
        if p.suffix in SUFFIXES
    ]
    files.append(Path(config.__file__))
    for path in files:
        text = path.read_text()
        if old in text:
            path.write_text(text.replace(old, new))
            print(f"{text.count(old):4}  {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
