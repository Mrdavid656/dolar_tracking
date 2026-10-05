"""Reading and writing the data/rates.csv dataset.

The functions that touch the disk (append_rows, read_rows) are kept apart from
the ones that only transform data (to_record, to_row, group_readings).
"""

import csv
from collections.abc import Iterable
from itertools import groupby
from operator import attrgetter
from pathlib import Path

from .models import Quote, Reading, Row

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "rates.csv"
COLUMNS = ("timestamp", "bank", "buy", "sell", "official")


def to_record(row: Row) -> dict:
    """Row -> dictionary keyed by the CSV columns."""
    return {"timestamp": row.timestamp, "bank": row.bank, **row.quote._asdict()}


def to_row(record: dict) -> Row:
    """Dictionary read from the CSV -> Row (empty cells become None)."""
    quote = Quote(*(float(record[field]) if record[field] else None for field in Quote._fields))
    return Row(record["timestamp"], record["bank"], quote)


def group_readings(rows: Iterable[Row]) -> tuple[Reading, ...]:
    """Group the rows by run, in chronological order."""
    by_timestamp = attrgetter("timestamp")
    return tuple(
        Reading(timestamp, {row.bank: row.quote for row in group})
        for timestamp, group in groupby(sorted(rows, key=by_timestamp), key=by_timestamp)
    )


def append_rows(rows: Iterable[Row], path: Path = CSV_PATH) -> None:
    path.parent.mkdir(exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerows(map(to_record, rows))


def read_rows(path: Path = CSV_PATH) -> tuple[Row, ...]:
    with path.open(encoding="utf-8", newline="") as f:
        return tuple(map(to_row, csv.DictReader(f)))


def read_readings(path: Path = CSV_PATH) -> tuple[Reading, ...]:
    return group_readings(read_rows(path))
