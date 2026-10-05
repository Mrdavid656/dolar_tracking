"""Fill in the sources missing from the latest reading, querying them from this machine.

Usage: python -m dolar_market.backfill

Some sites refuse connections from GitHub's servers. This script is meant to run
on a computer in Bolivia shortly after each scheduled reading: it queries only the
sources that reading lacks and appends them with the reading's own timestamp, so
they join it. It does nothing when the reading is complete or too old to patch.
"""

import sys
from datetime import datetime, timedelta

from .analysis import missing_sources
from .models import Reading
from .scrape import BOLIVIA, query_all, report_line, to_rows
from .sources import SOURCES
from .storage import append_rows, read_readings

MAX_AGE = timedelta(hours=3)  # older than this, a fresh quote no longer describes that reading


def is_recent(reading: Reading, now: datetime, max_age: timedelta = MAX_AGE) -> bool:
    return now - datetime.fromisoformat(reading.timestamp) <= max_age


def main() -> int:
    latest = read_readings()[-1]
    missing = missing_sources(latest, SOURCES)
    if not missing:
        print(f"Reading {latest.timestamp} is complete; nothing to backfill.")
        return 0
    if not is_recent(latest, datetime.now(BOLIVIA)):
        print(f"Reading {latest.timestamp} is older than {MAX_AGE}; not backfilling {', '.join(missing)}.")
        return 0
    results = query_all({name: SOURCES[name] for name in missing})
    rows = to_rows(latest.timestamp, results)
    append_rows(rows)
    print("\n".join(map(report_line, results)))
    print(f"\n{len(rows)}/{len(missing)} missing sources added to reading {latest.timestamp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
