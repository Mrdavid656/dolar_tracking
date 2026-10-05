"""Immutable data types shared by every module."""

from collections.abc import Mapping
from typing import NamedTuple


class Quote(NamedTuple):
    """Bolivianos per dollar. None means the source does not publish that value."""

    buy: float | None = None
    sell: float | None = None
    official: float | None = None


class Row(NamedTuple):
    """What one bank published at a given moment: one line of the CSV."""

    timestamp: str
    bank: str
    quote: Quote


class Reading(NamedTuple):
    """Every quote collected in a single run."""

    timestamp: str
    banks: Mapping[str, Quote]
