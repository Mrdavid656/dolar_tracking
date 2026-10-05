"""Generate dashboard.html from data/rates.csv.

Usage: python -m dolar_market.dashboard
"""

import json
from collections.abc import Iterable, Sequence
from pathlib import Path

from .models import Reading
from .sources import SOURCES
from .storage import read_readings

TEMPLATE = Path(__file__).with_name("dashboard_template.html")
OUTPUT = Path(__file__).resolve().parent.parent / "dashboard.html"
MARKER = "/*DATA*/"


def to_payload(readings: Sequence[Reading], sources: Iterable[str]) -> dict:
    """The structure consumed by the template's JavaScript."""
    return {
        "sources": list(sources),
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


def main() -> None:
    readings = read_readings()
    page = embed(TEMPLATE.read_text(encoding="utf-8"), to_payload(readings, SOURCES))
    OUTPUT.write_text(page, encoding="utf-8")
    print(f"{len(readings)} readings -> {OUTPUT}")


if __name__ == "__main__":
    main()
