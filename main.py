"""Entry point: ``python main.py [--dry-run] [--no-telegram]``."""

import sys

from goldsilver.cli import main

if __name__ == "__main__":
    sys.exit(main())
