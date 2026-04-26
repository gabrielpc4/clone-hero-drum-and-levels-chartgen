from __future__ import annotations

import argparse
from pathlib import Path

from classification_logic import apply_classification_report
from classification_logic import build_classification_report
from classification_logic import default_repo_root
from classification_logic import report_summary_lines
from classification_logic import write_report_json


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply the reusable SOAD difficulty classification to song.ini files."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=default_repo_root(),
        help="Repository root. Defaults to the current Clone Hero repo.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=default_repo_root() / "tools" / "difficulty_classification" / "latest_applied_difficulties.json",
        help="Where to write the classification JSON used for the run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the report but do not rewrite any song.ini files.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    report = build_classification_report(arguments.repo_root)
    write_report_json(report, arguments.output_json)

    if not arguments.dry_run:
        apply_classification_report(report)

    for summary_line in report_summary_lines(report):
        print(summary_line)

    print(f"dry_run={arguments.dry_run}")
    print(f"report_json={arguments.output_json}")


if __name__ == "__main__":
    main()

