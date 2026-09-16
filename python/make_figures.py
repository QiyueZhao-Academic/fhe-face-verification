#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Draws the figures of the study from the benchmark record.

    python3 python/make_figures.py --results artifacts/results.json --out-dir reports

Every figure is drawn from that record and from the per-pair scores. The prose of
the report is written by hand and is not generated here.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ffv import figures  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", default="artifacts/results.json")
    parser.add_argument("--scores", default="artifacts/scores.csv")
    parser.add_argument("--out-dir", default="reports")
    args = parser.parse_args()

    if not os.path.isfile(args.results):
        raise SystemExit(
            f"{args.results} is absent; run ffv_bench before drawing the figures"
        )
    with open(args.results, encoding="utf-8") as handle:
        results = json.load(handle)
    if results.get("schema") != "ffv-results-1":
        raise SystemExit(
            f"{args.results} declares schema '{results.get('schema')}' and this generator reads "
            "'ffv-results-1'"
        )

    figure_dir = os.path.join(args.out_dir, "figures")
    made, skipped = figures.generate(results, args.scores, figure_dir)
    print(f"figures : {len(made)} written to {figure_dir}")
    for name in sorted(made):
        print(f"          {os.path.basename(made[name])}")
    if skipped:
        print(f"          {len(skipped)} skipped for absent inputs: {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
