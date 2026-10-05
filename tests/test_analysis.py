from dolar_market.analysis import (
    Deal,
    average_gap,
    best_buy,
    best_sell,
    failing_sources,
    missing_sources,
    official_of,
    parallel_of,
    priced_banks,
)
from dolar_market.models import Quote, Reading

READING = Reading(
    "2026-10-05T07:00:00-04:00",
    {
        "BCB": Quote(official=12.0),
        "Parallel": Quote(buy=11.98, sell=12.02),
        "Alpha": Quote(buy=11.5, sell=12.3, official=12.0),
        "Beta": Quote(buy=11.7, sell=12.1),
        "Gamma": Quote(buy=11.7, sell=12.3),
        "Delta": Quote(sell=12.1),
    },
)
BANKS = priced_banks(READING)


def test_priced_banks_excludes_references_and_sorts_by_cheapest_sell():
    assert [name for name, _ in BANKS] == ["Beta", "Delta", "Gamma", "Alpha"]


def test_best_sell_is_the_lowest_sell_price():
    assert best_sell(BANKS) == Deal(12.1, ("Beta", "Delta"))


def test_best_buy_is_the_highest_buy_price():
    assert best_buy(BANKS) == Deal(11.7, ("Beta", "Gamma"))


def test_best_deals_are_empty_without_banks():
    assert best_buy(()) == Deal(None, ())
    assert best_sell(()) == Deal(None, ())


def test_references():
    assert official_of(READING) == 12.0
    assert parallel_of(READING) == 12.0
    assert parallel_of(Reading("t", {})) is None


def test_official_falls_back_to_what_a_bank_shows():
    assert official_of(Reading("t", {"Alpha": Quote(official=11.9)})) == 11.9


def test_average_gap_counts_only_banks_with_both_prices():
    gap, count = average_gap(BANKS)
    assert count == 3
    assert round(gap, 4) == round((0.8 + 0.4 + 0.6) / 3, 4)


def test_missing_sources():
    assert missing_sources(READING, ["Alpha", "Omega"]) == ("Omega",)


def reading(*names):
    return Reading("t", {name: Quote(sell=12.0) for name in names})


def test_failing_sources_needs_consecutive_misses():
    history = [reading("A", "B"), reading("A"), reading("A"), reading("A")]
    assert failing_sources(history, ["A", "B"], threshold=3) == ("B",)
    assert failing_sources(history[:3], ["A", "B"], threshold=3) == ()


def test_failing_sources_ignores_sources_never_seen():
    history = [reading("A"), reading("A"), reading("A")]
    assert failing_sources(history, ["A", "New"], threshold=3) == ()
