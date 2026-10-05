"""Generate the dashboard from data/rates.csv.

Usage: python -m dolar_market.dashboard

Writes the dashboard twice, with the same content, plus the privacy policy:
    dashboard.html     the page body alone, as an artifact host expects it
    site/index.html    a complete HTML document, served by GitHub Pages
    site/privacy.html  a copy of privacy.html
    site/rates.csv     a copy of the dataset, for readers to download
and copies the share image and the icon from static/ into site/.

Optional environment variables: SUBSCRIBE_URL adds a "subscribe" button and
CONTACT_EMAIL overrides the address shown in the footer.
"""

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from .models import Reading
from .sources import SOURCES, Source
from .storage import CSV_PATH, read_readings

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).with_name("dashboard_template.html")
FRAGMENT_OUTPUT = ROOT / "dashboard.html"
SITE_OUTPUT = ROOT / "site" / "index.html"
PRIVACY_PAGE = Path(__file__).with_name("privacy.html")
STATIC = Path(__file__).with_name("static")
STATIC_FILES = ("og.png", "favicon.svg")  # og_image.html is only the source of og.png
SITE_URL = "https://mrdavid656.github.io/dolar_tracking/"
PRIVACY_URL = SITE_URL + "privacy.html"
DATA_URL = SITE_URL + CSV_PATH.name
SITE_TITLE = "Pizarra del Dólar"
SITE_DESCRIPTION = (
    "Compra y venta del dólar en los bancos de Bolivia, junto al oficial del BCB y el paralelo. "
    "Actualizado tres veces al día."
)
MARKER = "/*DATA*/"
CONTACT_EMAIL = "davidgemio98@gmail.com"
DOCUMENT = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<meta name="theme-color" content="#0d0f0e">
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="canonical" href="{site_url}">
<!-- Open Graph: the card shown when the link is shared -->
<meta property="og:type" content="website">
<meta property="og:locale" content="es_BO">
<meta property="og:site_name" content="{title}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{site_url}">
<meta property="og:image" content="{site_url}og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{title}">
<meta name="twitter:card" content="summary_large_image">
<style>body {{ margin: 0; }} [hidden] {{ display: none !important; }}</style>
</head>
<body>
{body}
</body>
</html>
"""


def to_payload(
    readings: Sequence[Reading],
    sources: Mapping[str, Source],
    subscribe_url: str | None = None,
    contact_email: str | None = CONTACT_EMAIL,
    privacy_url: str | None = PRIVACY_URL,
    data_url: str | None = DATA_URL,
) -> dict:
    """The structure consumed by the template's JavaScript."""
    return {
        "sources": list(sources),
        "pages": {name: source.page for name, source in sources.items() if source.page},
        "dataUrl": data_url or None,
        "subscribeUrl": subscribe_url or None,
        "contactEmail": contact_email or None,
        "privacyUrl": privacy_url or None,
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
    return DOCUMENT.format(body=fragment, title=SITE_TITLE, description=SITE_DESCRIPTION, site_url=SITE_URL)


def main() -> None:
    readings = read_readings()
    env = os.environ
    payload = to_payload(readings, SOURCES, env.get("SUBSCRIBE_URL"), env.get("CONTACT_EMAIL") or CONTACT_EMAIL)
    fragment = embed(TEMPLATE.read_text(encoding="utf-8"), payload)
    FRAGMENT_OUTPUT.write_text(fragment, encoding="utf-8")
    SITE_OUTPUT.parent.mkdir(exist_ok=True)
    SITE_OUTPUT.write_text(to_document(fragment), encoding="utf-8")
    (SITE_OUTPUT.parent / PRIVACY_PAGE.name).write_text(PRIVACY_PAGE.read_text(encoding="utf-8"), encoding="utf-8")
    (SITE_OUTPUT.parent / CSV_PATH.name).write_bytes(CSV_PATH.read_bytes())
    for name in STATIC_FILES:
        (SITE_OUTPUT.parent / name).write_bytes((STATIC / name).read_bytes())
    print(f"{len(readings)} readings -> {FRAGMENT_OUTPUT} and {SITE_OUTPUT}")


if __name__ == "__main__":
    main()
