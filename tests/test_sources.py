"""Each source's parser, run against a saved copy of the real response."""

import gzip
import json

import pytest

from dolar_market.models import Quote
from dolar_market.sources import SOURCES, extract, make_quote, to_number, to_plain_text

from .capture_fixtures import EXPECTED, fixture_path

EXPECTED_QUOTES = json.loads(EXPECTED.read_text(encoding="utf-8"))


def test_every_source_has_a_fixture():
    assert set(EXPECTED_QUOTES) == set(SOURCES)


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_parser_reads_saved_response(name):
    body = gzip.decompress(fixture_path(name).read_bytes())
    assert SOURCES[name].parse(body) == Quote(**EXPECTED_QUOTES[name])


@pytest.mark.parametrize(
    ("value", "number"),
    [("12,30", 12.3), ("12.30", 12.3), (12, 12.0), ("7", 7.0), (None, None)],
)
def test_to_number_accepts_both_decimal_separators(value, number):
    assert to_number(value) == number


def test_to_plain_text_drops_tags_scripts_and_entities():
    page = "<p>D&oacute;lar <b>Compra</b>:\n 11.50</p><script>var x = 99;</script><style>p{}</style>"
    assert to_plain_text(page).strip() == "Dólar Compra : 11.50"


def test_extract_leaves_missing_values_as_none():
    quote = extract("Venta 12,35", sell=r"Venta (\d+(?:[.,]\d+)?)", buy=r"Compra (\d+)")
    assert quote == Quote(buy=None, sell=12.35, official=None)


def test_make_quote_converts_strings():
    assert make_quote("11,5", 12, None) == Quote(11.5, 12.0, None)
