"""Print what failed in each of the last readings, one per line.

Usage: python -m dolar_market.monitor

A line is a source missing altogether ("Prodem") or a value a source used to
publish and no longer does ("Banco Unión (sell)"). The workflow turns each line
into a GitHub issue and closes the issues whose line is no longer printed.
"""

from .analysis import failing_fields, failing_sources
from .sources import SOURCES
from .storage import read_readings


def main() -> None:
    readings = read_readings()
    print("\n".join(failing_sources(readings, SOURCES) + failing_fields(readings, SOURCES)))


if __name__ == "__main__":
    main()
