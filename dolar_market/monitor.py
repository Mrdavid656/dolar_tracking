"""Print the sources that failed in each of the last readings, one per line.

Usage: python -m dolar_market.monitor

The workflow turns each printed name into a GitHub issue and closes the issues
of sources that are no longer printed.
"""

from .analysis import failing_sources
from .sources import SOURCES
from .storage import read_readings


def main() -> None:
    print("\n".join(failing_sources(read_readings(), SOURCES)))


if __name__ == "__main__":
    main()
