"""Query every source and append one row per bank to data/rates.csv.

Usage: python -m dolar_market.scrape [--if-older-than MINUTES]

With --if-older-than the reading is taken only when the latest saved one is older
than that. It lets two schedulers back each other up (GitHub's and a computer's)
without both saving a reading for the same slot.
"""

import argparse
import sys
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from .models import Quote, Reading, Row
from .sources import SOURCES, Source
from .storage import CSV_PATH, append_rows, read_readings

BOLIVIA = timezone(timedelta(hours=-4))  # Bolivia has no daylight saving time
VALID_RANGE = (5, 50)  # Bs per dollar; anything outside means the site changed
ATTEMPTS = 2


class Result(NamedTuple):
    """What a source returned: its quote or the reason it failed."""

    bank: str
    quote: Quote | None = None
    error: str | None = None


# --- Pure functions ------------------------------------------------------------


def problem(quote: Quote) -> str | None:
    """Return why the quote is not credible, or None if it is valid."""
    present = tuple(v for v in quote if v is not None)
    out_of_range = tuple(v for v in present if not VALID_RANGE[0] <= v <= VALID_RANGE[1])
    if not present:
        return "no value found on the page"
    if out_of_range:
        return f"values out of range: {list(out_of_range)}"
    return None


def is_recent(reading: Reading, now: datetime, max_age: timedelta) -> bool:
    return now - datetime.fromisoformat(reading.timestamp) <= max_age


def to_rows(timestamp: str, results: Iterable[Result]) -> tuple[Row, ...]:
    return tuple(Row(timestamp, r.bank, r.quote) for r in results if r.quote)


def report_line(result: Result) -> str:
    if result.quote is None:
        return f"FAIL  {result.bank:22} {result.error}"
    q = result.quote
    return f"OK    {result.bank:22} buy={q.buy} sell={q.sell} official={q.official}"


# --- Effects: network, clock and disk -------------------------------------------


def attempt(bank: str, get_quote: Source) -> Result:
    """Query a source once. Never raises."""
    try:
        quote = get_quote()
    except Exception as e:  # one broken source must not take down the others
        return Result(bank, error=f"{type(e).__name__}: {e}")
    error = problem(quote)
    return Result(bank, error=error) if error else Result(bank, quote)


def query(bank: str, get_quote: Source, attempts: int = ATTEMPTS) -> Result:
    """Query a source, retrying while it fails and attempts remain."""
    result = attempt(bank, get_quote)
    if result.quote or attempts <= 1:
        return result
    return query(bank, get_quote, attempts - 1)


def query_all(sources: Mapping[str, Source]) -> tuple[Result, ...]:
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        return tuple(pool.map(lambda pair: query(*pair), sources.items()))


def now_in_bolivia() -> str:
    return datetime.now(BOLIVIA).replace(microsecond=0).isoformat()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Take a reading of every source.")
    parser.add_argument("--if-older-than", type=int, metavar="MINUTES", help="skip when the latest reading is newer")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    max_age = parse_args(argv).if_older_than
    readings = read_readings() if max_age is not None and CSV_PATH.exists() else ()
    if readings and is_recent(readings[-1], datetime.now(BOLIVIA), timedelta(minutes=max_age)):
        print(f"Reading {readings[-1].timestamp} is under {max_age} minutes old; not taking another.")
        return 0
    results = query_all(SOURCES)
    rows = to_rows(now_in_bolivia(), results)
    append_rows(rows)
    print("\n".join(map(report_line, results)))
    print(f"\n{len(rows)}/{len(SOURCES)} sources saved to {CSV_PATH}")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
