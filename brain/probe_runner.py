"""Background entry point for machine probe (called by reconcile.py as Popen)."""

import sys
from .probe import run

if __name__ == "__main__":
    hostname = sys.argv[1] if len(sys.argv) > 1 else None
    cwd = sys.argv[2] if len(sys.argv) > 2 else None
    run(hostname=hostname, cwd=cwd)
