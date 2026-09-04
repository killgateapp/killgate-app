#!/usr/bin/env python3
"""Print Killgate production/release readiness without printing any secret values."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make direct execution from the repository root reliable without requiring
# an editable install or PYTHONPATH mutation in deployment tooling.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.readiness import readiness_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--release",
        action="store_true",
        help="also fail when owner/Play release values are still missing",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    report = readiness_report()
    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print("Runtime:", "READY" if report.runtime_ready else "NOT READY")
        for item in report.runtime_blockers:
            print("  BLOCK:", item)
        print("Play release:", "READY" if report.release_ready else "NOT READY")
        for item in report.release_blockers:
            print("  RELEASE BLOCK:", item)
        for item in report.warnings:
            print("  WARN:", item)

    return 0 if (report.release_ready if args.release else report.runtime_ready) else 1


if __name__ == "__main__":
    raise SystemExit(main())
