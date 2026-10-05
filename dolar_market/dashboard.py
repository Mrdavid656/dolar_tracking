"""Generate the dashboard from data/rates.csv.

Usage: python -m dolar_market.dashboard

Writes two files with the same content:
    dashboard.html   the page body alone, as an artifact host expects it
    site/index.html  a complete HTML document, served by GitHub Pages

The optional SUBSCRIBE_URL environment variable adds a "subscribe" link.
"""

import json
import os
from collections.abc import Iterable, Sequence
from pathlib import Path

from .models import Reading
from .sources import SOURCES
from .storage import read_readings

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).with_name("dashboard_template.html")
FRAGMENT_OUTPUT = ROOT / "dashboard.html"
SITE_OUTPUT = ROOT / "site" / "index.html"
MARKER = "/*DATA*/"
DOCUMENT = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body {{ margin: 0; }}</style>
</head>
<body>
{body}
</body>
</html>
"""


def to_payload(readings: Sequence[Reading], sources: Iterable[str], subscribe_url: str | None = None) -> dict:
    """The structure consumed by the template's JavaScript."""
    return {
        "sources": list(sources),
        "subscribeUrl": subscribe_url or None,
        "readings": [
            {
                "t": reading.timestamp,
                "banks": {bank: quote._asdict() for bank, quote in reading.banks.items()},
            }
            for reading in readings
        ],
    }


def embed(template: str, payload: dict) -> str:
    """Insert the payload as JSON at the template's marker."""
    # "</" is escaped so the JSON can never close the <script> tag
    as_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return template.replace(MARKER, as_json, 1)


def to_document(fragment: str) -> str:
    """Wrap the page body in a complete HTML document."""
    return DOCUMENT.format(body=fragment)


def main() -> None:
    readings = read_readings()
    payload = to_payload(readings, SOURCES, os.environ.get("SUBSCRIBE_URL"))
    fragment = embed(TEMPLATE.read_text(encoding="utf-8"), payload)
    FRAGMENT_OUTPUT.write_text(fragment, encoding="utf-8")
    SITE_OUTPUT.parent.mkdir(exist_ok=True)
    SITE_OUTPUT.write_text(to_document(fragment), encoding="utf-8")
    print(f"{len(readings)} readings -> {FRAGMENT_OUTPUT} and {SITE_OUTPUT}")


if __name__ == "__main__":
    main()
