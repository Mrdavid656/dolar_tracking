"""Pure functions that answer questions about readings.

Nothing here touches the network, the disk or the clock.
"""

from collections.abc import Iterable, Sequence
from typing import NamedTuple

from .models import Quote, Reading
from .sources import OFFICIAL_SOURCE, PARALLEL_SOURCE, REFERENCE_SOURCES

Banks = Sequence[tuple[str, Quote]]


class Deal(NamedTuple):
    """The best price of a kind and every bank that offers it."""

    price: float | None
    banks: tuple[str, ...]


def official_of(reading: Reading) -> float | None:
    """The official rate: the BCB's own figure, or what any bank shows as official."""
    own = reading.banks.get(OFFICIAL_SOURCE, Quote()).official
    others = (q.official for q in reading.banks.values() if q.official is not None)
    return own if own is not None else next(others, None)


def parallel_of(reading: Reading) -> float | None:
    """The parallel-market rate: midpoint between its buy and sell prices."""
    quote = reading.banks.get(PARALLEL_SOURCE, Quote())
    present = tuple(v for v in (quote.buy, quote.sell) if v is not None)
    return sum(present) / len(present) if present else None


def priced_banks(reading: Reading) -> tuple[tuple[str, Quote], ...]:
    """Banks that publish buy or sell, cheapest seller first (references excluded)."""
    banks = (
        (name, q)
        for name, q in reading.banks.items()
        if name not in REFERENCE_SOURCES and (q.buy is not None or q.sell is not None)
    )
    return tuple(sorted(banks, key=lambda p: (p[1].sell is None, p[1].sell or 0, -(p[1].buy or 0), p[0])))


def best_buy(banks: Banks) -> Deal:
    """Best deal for someone selling dollars: the HIGHEST buy price."""
    price = max((q.buy for _, q in banks if q.buy is not None), default=None)
    return Deal(price, tuple(name for name, q in banks if price is not None and q.buy == price))


def best_sell(banks: Banks) -> Deal:
    """Best deal for someone buying dollars: the LOWEST sell price."""
    price = min((q.sell for _, q in banks if q.sell is not None), default=None)
    return Deal(price, tuple(name for name, q in banks if price is not None and q.sell == price))


def average_gap(banks: Banks) -> tuple[float | None, int]:
    """Mean of sell minus buy, and how many banks publish both values."""
    gaps = tuple(q.sell - q.buy for _, q in banks if q.buy is not None and q.sell is not None)
    return (sum(gaps) / len(gaps) if gaps else None), len(gaps)


def missing_sources(reading: Reading, sources: Iterable[str]) -> tuple[str, ...]:
    return tuple(name for name in sources if name not in reading.banks)


def failing_sources(readings: Sequence[Reading], sources: Iterable[str], threshold: int = 3) -> tuple[str, ...]:
    """Sources absent from each of the last `threshold` readings.

    A source that has never produced a row is not reported: it was just added
    and has no history to compare against.
    """
    recent = readings[-threshold:]
    if len(recent) < threshold:
        return ()
    seen_before = {name for reading in readings for name in reading.banks}
    return tuple(
        name
        for name in sources
        if name in seen_before and all(name not in reading.banks for reading in recent)
    )
