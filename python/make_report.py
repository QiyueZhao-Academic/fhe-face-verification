#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generates the PDF and Markdown report from the benchmark record.

    python3 python/make_report.py --results artifacts/results.json --out-dir reports

Every number in the report is read from that file. A metric the run declined to
emit stops the generation with a message naming the path, so the report never
carries a placeholder.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ffv import figures, report  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", default="artifacts/results.json")
    parser.add_argument("--scores", default="artifacts/scores.csv")
    parser.add_argument("--protocol", default="artifacts/session/protocol.json",
                        help="record of the two-process round trip, included when present")
    parser.add_argument("--out-dir", default="reports")
    parser.add_argument("--name", default="report")
    parser.add_argument("--author", default=os.environ.get("FFV_AUTHOR", report.AUTHOR),
                        help="name printed under the title")
    parser.add_argument("--repo", default=os.environ.get("FFV_REPO_URL", ""),
                        help="repository URL printed under the author line; also read from "
                             "the FFV_REPO_URL environment variable")
    args = parser.parse_args()

    if not os.path.isfile(args.results):
        raise SystemExit(
            f"{args.results} is absent; run ffv_bench before generating the report"
        )
    with open(args.results, encoding="utf-8") as handle:
        results = json.load(handle)
    if results.get("schema") != "ffv-results-1":
        raise SystemExit(
            f"{args.results} declares schema '{results.get('schema')}' and this generator reads "
            "'ffv-results-1'"
        )

    protocol = None
    if os.path.isfile(args.protocol):
        with open(args.protocol, encoding="utf-8") as handle:
            protocol = json.load(handle)

    figure_dir = os.path.join(args.out_dir, "figures")
    made, skipped = figures.generate(results, args.scores, figure_dir)
    print(f"figures : {len(made)} written to {figure_dir}")
    if skipped:
        print(f"          {len(skipped)} skipped for absent inputs: {', '.join(skipped)}")

    try:
        blocks, slots = report.build(results, protocol, made, skipped)
    except KeyError as error:
        raise SystemExit(f"the report cannot be generated: {error.args[0]}")

    os.makedirs(args.out_dir, exist_ok=True)
    pdf = report.render_pdf(blocks, os.path.join(args.out_dir, f"{args.name}.pdf"), results,
                            repo_url=args.repo, author=args.author)
    markdown = report.render_markdown(
        blocks, os.path.join(args.out_dir, f"{args.name}.md"), results,
        repo_url=args.repo, author=args.author
    )
    inventory = report.render_slots(slots, os.path.join(args.out_dir, "data_slots.md"))
    print(f"pdf     : {pdf} ({os.path.getsize(pdf) / 1024:.0f} KiB)")
    print(f"markdown: {markdown}")
    print(f"slots   : {inventory} ({len(slots.records)} filled from the run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
