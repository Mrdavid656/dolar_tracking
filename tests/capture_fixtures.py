"""Download the current response of every source and save it as a test fixture.

Usage: python -m tests.capture_fixtures [source name ...]

Run it when a site changes its markup and the source has been fixed: it refreshes
tests/fixtures/<slug>.gz and the values the parser is expected to return.
With no arguments every source is captured.
"""

import gzip
import json
import re
import sys
import unicodedata
from pathlib import Path

from dolar_market.sources import SOURCES, fetch

FIXTURES = Path(__file__).with_name("fixtures")
EXPECTED = FIXTURES / "expected.json"


def slug(name: str) -> str:
    """File-safe version of a source name: "Banco Unión" -> "banco_union"."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")


def fixture_path(name: str) -> Path:
    return FIXTURES / f"{slug(name)}.gz"


def main() -> None:
    names = sys.argv[1:] or list(SOURCES)
    expected = json.loads(EXPECTED.read_text(encoding="utf-8")) if EXPECTED.exists() else {}
    FIXTURES.mkdir(exist_ok=True)
    for name in names:
        source = SOURCES[name]
        body = fetch(source.url, **source.request).content
        fixture_path(name).write_bytes(gzip.compress(body))
        expected[name] = source.parse(body)._asdict()
        print(f"{name}: {expected[name]}")
    EXPECTED.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
