"""The quote sources, declared as data.

SOURCES maps each name to a Source: where to download from and a pure `parse`
function that turns the raw response into a Quote. Calling a Source performs the
download (the only side effect in this module) and parses it. If a site changes,
only its entry fails; the rest keep working.
"""

import html
import json
import re
import ssl
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import NamedTuple

import requests
from requests.adapters import HTTPAdapter

from .models import Quote

# Names of the sources that are market references rather than banks.
OFFICIAL_SOURCE = "BCB"
PARALLEL_SOURCE = "Parallel"
REFERENCE_SOURCES = frozenset({OFFICIAL_SOURCE, PARALLEL_SOURCE})

HEADERS = MappingProxyType(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
        ),
        "Accept-Language": "es-BO,es;q=0.9",
    }
)
TIMEOUT = 30
NUM = r"(\d+(?:[.,]\d+)?)"

# Patterns shared by several sites ("Dólar Compra: 11.50", "Dólar Venta 12,30").
# The "." in "D.lar" tolerates the ó in any encoding.
BUY = rf"D.lar\s+Compra:?\s*{NUM}"
SELL = rf"D.lar\s+Venta:?\s*{NUM}"
OFFICIAL = rf"D.lar\s+Oficial:?\s*{NUM}"


# --- Interpretation: pure functions ------------------------------------------


def to_plain_text(page: str) -> str:
    """Reduce an HTML document to its visible text on a single line."""
    without_code = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", page)
    without_tags = re.sub(r"(?s)<[^>]+>", " ", without_code)
    return re.sub(r"\s+", " ", html.unescape(without_tags))


def to_number(value) -> float | None:
    """Convert 12, "12.30" or "12,30" to float; None stays None."""
    return None if value is None else float(str(value).replace(",", "."))


def find_number(text: str, pattern: str | None) -> float | None:
    """Return the number captured by the pattern, or None if it is absent."""
    match = re.search(pattern, text, flags=re.I) if pattern else None
    return to_number(match.group(1)) if match else None


def extract(text: str, buy=None, sell=None, official=None) -> Quote:
    """Build a Quote by searching the text with one pattern per value."""
    return Quote(find_number(text, buy), find_number(text, sell), find_number(text, official))


def make_quote(buy=None, sell=None, official=None) -> Quote:
    """Build a Quote from values that are already separated (e.g. from JSON)."""
    return Quote(to_number(buy), to_number(sell), to_number(official))


# --- Download: the only side effect -------------------------------------------


class _LegacyTLSAdapter(HTTPAdapter):
    """Adapter for servers that reset the connection under Python's default TLS."""

    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.set_ciphers("DEFAULT:@SECLEVEL=1")
        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)


def fetch(url, method="GET", legacy_tls=False, headers=HEADERS, **request) -> requests.Response:
    with requests.Session() as session:
        if legacy_tls:
            session.mount("https://", _LegacyTLSAdapter())
        response = session.request(method, url, headers=dict(headers), timeout=TIMEOUT, **request)
    response.raise_for_status()
    return response


# --- Sources: a download description plus a pure parser -----------------------


class Source(NamedTuple):
    """Where a quote comes from and how to read it."""

    url: str
    parse: Callable[[bytes], Quote]  # pure: raw response body -> Quote
    request: Mapping = MappingProxyType({})  # extra arguments for `fetch`
    page: str = ""  # where a reader can see the figure

    def __call__(self) -> Quote:
        return self.parse(fetch(self.url, **self.request).content)


def from_html(url: str, legacy_tls=False, **patterns) -> Source:
    """Source whose page is searched, as visible text, for one pattern per value."""

    def parse(body: bytes) -> Quote:
        return extract(to_plain_text(body.decode("utf-8", errors="replace")), **patterns)

    return Source(url, parse, {"legacy_tls": legacy_tls}, url)


def from_json(url: str, read: Callable[[dict], Quote], page: str, **request) -> Source:
    """Source that answers with JSON, turned into a Quote by `read`.

    `page` is the site a person would open to see the same figure.
    """

    def parse(body: bytes) -> Quote:
        return read(json.loads(body))

    return Source(url, parse, request, page)


SOURCES: MappingProxyType[str, Source] = MappingProxyType(
    {
        OFFICIAL_SOURCE: from_html(
            "https://www.bcb.gob.bo/",
            official=rf"Tipo de cambio oficial.{{0,200}}?Bs\W{{0,10}}{NUM}",
        ),
        "BNB": from_html(
            "https://www.bnb.com.bo/PortalBNB/Principal/BancaPersonas",
            buy=BUY,
            sell=SELL,
            official=OFFICIAL,
        ),
        "BCP": from_html("https://www.bcp.com.bo/", legacy_tls=True, buy=BUY, sell=SELL),
        "BISA": from_html("https://www.bisa.com/home", buy=BUY, sell=SELL),
        "Mercantil Santa Cruz": from_json(
            "https://backportal.bmsc.com.bo:1443/api/bmscservices/tipotre",
            lambda d: make_quote(d["compra"], d["venta"], d["oficial"]),
            page="https://www.bmsc.com.bo/",
        ),
        "Banco Unión": from_html(
            "https://www.bancounion.com.bo/",
            buy=rf"Compra BOB:\s*{NUM}",
            sell=rf"Compra BOB:\s*[\d.,]+\s*/\s*Venta\s*{NUM}",
            official=OFFICIAL,
        ),
        # Ganadero only publishes a reference sell value.
        "Ganadero": from_html(
            "https://www.bg.com.bo/personas/",
            sell=rf"Valor Ref\. Venta USD\s*{NUM}",
            official=rf"T\. Cambio Oficial\s*{NUM}",
        ),
        "Económico": from_json(
            "https://www.baneco.com.bo/GetTipoCambio",
            lambda d: make_quote(d["Compra"], d["Venta"], d["Oficial"]),
            page="https://www.baneco.com.bo/",
        ),
        "FIE": from_json(
            "https://www.bancofie.com.bo/api/tcl",
            lambda d: extract(d["resultado"]["documento"], BUY, SELL, OFFICIAL),
            page="https://www.bancofie.com.bo/",
            method="POST",
            json={},
            headers={
                **HEADERS,
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://www.bancofie.com.bo",
                "Referer": "https://www.bancofie.com.bo/",
            },
        ),
        "BancoSol": from_html(
            "https://www.bancosol.com.bo/",
            buy=rf"Tipo de cambio compra\s*:\s*{NUM}",
            sell=rf"Tipo de cambio venta\s*:\s*{NUM}",
            official=rf"estadounidense\s*:\s*{NUM}",
        ),
        "Fortaleza": from_json(
            "https://www.bancofortaleza.com.bo/proxy-exchange.php",
            lambda d: make_quote(
                d["response"]["buyExchange"],
                d["response"]["saleExchange"],
                d["response"]["officialExchange"],
            ),
            page="https://www.bancofortaleza.com.bo/",
        ),
        # Parallel market: USDT/BOB on Binance P2P, as aggregated by CriptoYa.
        # "bid" is what the market pays for a dollar and "ask" what it charges.
        PARALLEL_SOURCE: from_json(
            "https://criptoya.com/api/binancep2p/USDT/BOB/1",
            lambda d: make_quote(buy=d["bid"], sell=d["ask"]),
            page="https://criptoya.com/bo",
        ),
        "Prodem": from_html(
            "https://www.prodem.bo/Inicio",
            buy=rf"Banco Prodem Compra\s*{NUM}",
            sell=rf"Banco Prodem Compra\s*[\d.,]+\s*Venta\s*{NUM}",
            official=rf"estadounidense\s*{NUM}",
        ),
    }
)
