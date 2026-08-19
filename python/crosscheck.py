#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Cross-checks the record and the report against each other.

Three independent things are verified.

  1. Internal consistency of results.json: derived quantities are recomputed from
     their inputs and compared, so a value that was assembled incorrectly is
     caught rather than carried into the report.

  2. Agreement between results.json and scores.csv: the metrics are recomputed
     from the per-pair scores and compared with the values the benchmark emitted.

  3. Agreement between the report and the record: every number appearing in
     report.md is looked for in the set of numbers derivable from results.json,
     so a figure that drifted out of a hand-written sentence is caught.

Exit status is non-zero when any check fails.
"""

import argparse
import csv
import json
import math
import os
import re
import sys

FAILURES = []
CHECKS = 0


def check(condition, what, detail=""):
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"  pass  {what}" + (f"  ({detail})" if detail else ""))
    else:
        FAILURES.append(what)
        print(f"  FAIL  {what}" + (f"  ({detail})" if detail else ""))


def close(a, b, tolerance=1e-9):
    if a is None or b is None:
        return False
    scale = max(1.0, abs(float(a)), abs(float(b)))
    return abs(float(a) - float(b)) <= tolerance * scale


def read_scores(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append(
                (
                    float(row["score_cleartext"]),
                    float(row["score_encrypted"]),
                    int(row["label"]) == 1,
                    int(row["fold"]),
                )
            )
    return rows


def check_internal(results):
    print("\n[1. internal consistency of results.json]")
    crypto = results["crypto"]
    equiv = results["equivalence"]

    check(
        crypto["total_coeff_bits"] == sum(crypto["coeff_modulus_bits"]),
        "the total modulus width equals the sum of the primes",
        f"{crypto['total_coeff_bits']} bits",
    )
    check(
        crypto["total_coeff_bits"] <= crypto["max_coeff_bits_at_this_degree"],
        "the modulus stays inside the security bound for this degree",
        f"{crypto['total_coeff_bits']} of {crypto['max_coeff_bits_at_this_degree']}",
    )
    check(
        crypto["slot_count"] == crypto["poly_modulus_degree"] // 2,
        "the slot count is half the polynomial degree",
    )
    block = crypto["slots_per_template"]
    check(
        block >= crypto["template_dim"] and (block & (block - 1)) == 0,
        "the template block is a power of two at least as large as the dimension",
        f"{block} slots for {crypto['template_dim']} dimensions",
    )
    check(
        crypto["max_batch"] == crypto["slot_count"] // block,
        "the batch capacity is the slot count divided by the block",
        f"{crypto['max_batch']}",
    )
    check(
        crypto["rotations_per_score"] == int(math.log2(block)),
        "the doubling fold uses log2(block) rotations",
        f"{crypto['rotations_per_score']}",
    )
    check(
        results["circuit_trace"]["chain_index_in"]
        - results["circuit_trace"]["chain_index_out"]
        == crypto["multiplicative_depth"],
        "the measured level drop equals the declared multiplicative depth",
    )
    check(
        close(equiv["precision_bits"], -math.log2(equiv["max_abs_error"]), 1e-9),
        "the precision in bits is the negative log of the largest error",
        f"{equiv['precision_bits']:.3f} bits",
    )
    check(
        close(equiv["error_over_margin"], equiv["max_abs_error"] / equiv["min_abs_margin"], 1e-9),
        "the ratio equals the largest error over the smallest margin",
        f"{equiv['error_over_margin']:.3e}",
    )
    check(
        equiv["proved_zero_flips"] == (equiv["error_over_margin"] < 1.0),
        "the zero-flip claim is made exactly when the ratio is below one",
    )
    if equiv["proved_zero_flips"]:
        check(
            equiv["observed_flips"] == 0,
            "a proved bound is accompanied by zero observed changes",
            f"{equiv['observed_flips']} observed",
        )

    for point in results["batching"]:
        check(
            close(
                point["amortised_ms_per_verification"],
                point["server_score"]["median_ms"] / point["batch"],
                1e-9,
            ),
            f"batch {point['batch']}: the amortised time is the total over the batch",
        )
        check(
            close(
                point["bytes_per_verification"],
                point["ciphertext_bytes"]["wire"] / point["batch"],
                1e-9,
            ),
            f"batch {point['batch']}: the amortised size is the ciphertext over the batch",
        )

    for point in results["scale_sweep"]:
        check(
            point["headroom_bits"] == point["last_prime_bits"] - point["scale_bits"],
            f"scale {point['scale_bits']}: headroom is the prime width less the scale",
        )
        if point["usable"]:
            check(
                close(point["precision_bits"], -math.log2(point["max_abs_error"]), 1e-9),
                f"scale {point['scale_bits']}: precision follows from the error",
            )

    for name in ("verification_cleartext", "verification_encrypted"):
        section = results[name]
        check(
            section["n_genuine"] + section["n_impostor"] == section["n_pairs"],
            f"{name}: the class counts sum to the pair count",
        )
        check(
            close(section["far_resolution"], 1.0 / section["n_impostor"], 1e-12),
            f"{name}: the rate resolution is one over the impostor count",
        )
        for point in section["operating_points"]:
            budget = math.floor(point["target_far"] * section["n_impostor"])
            check(
                point["resolvable"] == (budget >= 1),
                f"{name}: a target of {point['target_far']:g} is marked resolvable correctly",
            )
            check(
                point["well_conditioned"] == (budget >= 5),
                f"{name}: a target of {point['target_far']:g} is marked conditioned correctly",
            )
            if not point["resolvable"]:
                check(
                    point["tar"] is None,
                    f"{name}: an unresolvable target of {point['target_far']:g} carries no value",
                )


def recompute(rows, target_fars):
    """Recomputes the protocol metrics from the per-pair scores."""

    def grid(values):
        unique = sorted(set(values))
        if not unique:
            return []
        span = unique[-1] - unique[0]
        pad = 0.5 * span / len(unique) if span > 0 else 1.0
        return (
            [unique[0] - pad]
            + [0.5 * (unique[i - 1] + unique[i]) for i in range(1, len(unique))]
            + [unique[-1] + pad]
        )

    def accuracy(subset, tau):
        correct = sum(1 for score, _, genuine, _ in subset if (score >= tau) == genuine)
        return correct / len(subset) if subset else 0.0

    folds = max(row[3] for row in rows) + 1
    accuracies, thresholds = [], []
    for k in range(folds):
        train = [r for r in rows if r[3] != k]
        test = [r for r in rows if r[3] == k]
        if not train or not test:
            continue
        best_accuracy, best_tau = -1.0, 0.0
        for tau in grid([r[0] for r in train]):
            value = accuracy(train, tau)
            if value > best_accuracy:
                best_accuracy, best_tau = value, tau
        accuracies.append(accuracy(test, best_tau))
        thresholds.append(best_tau)

    mean = sum(accuracies) / len(accuracies) if accuracies else 0.0
    genuine = sorted((r[0] for r in rows if r[2]))
    impostor = sorted((r[0] for r in rows if not r[2]))
    # Area under the curve by the rank statistic with midranks for ties.
    merged = sorted([(r[0], r[2]) for r in rows])
    rank_sum, index = 0.0, 0
    while index < len(merged):
        end = index
        while end + 1 < len(merged) and merged[end + 1][0] == merged[index][0]:
            end += 1
        midrank = 0.5 * ((index + 1) + (end + 1))
        rank_sum += sum(midrank for k in range(index, end + 1) if merged[k][1])
        index = end + 1
    n_g, n_i = len(genuine), len(impostor)
    auc = (rank_sum - 0.5 * n_g * (n_g + 1)) / (n_g * n_i) if n_g and n_i else 0.0
    return {"accuracy_mean": mean, "auc": auc, "thresholds": thresholds}


def check_against_scores(results, scores_path):
    print("\n[2. results.json against scores.csv]")
    if not os.path.isfile(scores_path):
        check(False, f"{scores_path} is present")
        return
    rows = read_scores(scores_path)
    check(
        len(rows) == results["dataset"]["n_pairs"],
        "the score file holds one row per pair",
        f"{len(rows)} rows",
    )
    clear = [(r[0], r[1], r[2], r[3]) for r in rows]
    encrypted = [(r[1], r[1], r[2], r[3]) for r in rows]

    from_clear = recompute(clear, [])
    check(
        close(from_clear["accuracy_mean"], results["verification_cleartext"]["protocol"]["accuracy_mean"], 1e-9),
        "cleartext accuracy recomputed from the scores matches the record",
        f"{from_clear['accuracy_mean'] * 100:.4f}%",
    )
    check(
        close(from_clear["auc"], results["verification_cleartext"]["auc"], 1e-9),
        "cleartext area under the curve recomputed matches the record",
        f"{from_clear['auc']:.6f}",
    )
    from_enc = recompute(encrypted, [])
    check(
        close(from_enc["accuracy_mean"], results["verification_encrypted"]["protocol"]["accuracy_mean"], 1e-9),
        "encrypted accuracy recomputed from the scores matches the record",
        f"{from_enc['accuracy_mean'] * 100:.4f}%",
    )

    worst = max(abs(r[1] - r[0]) for r in rows)
    check(
        close(worst, results["equivalence"]["max_abs_error"], 1e-9),
        "the largest score error recomputed matches the record",
        f"{worst:.3e}",
    )
    genuine = sum(1 for r in rows if r[2])
    check(
        genuine == results["dataset"]["n_genuine"],
        "the genuine pair count in the score file matches the record",
        f"{genuine}",
    )


# Scientific notation is matched first and whole, so the exponent of "1e-02" is
# never mistaken for a separate number.
NUMBER = re.compile(
    r"(?<![\w.,])(\d+(?:\.\d+)?e[+-]?\d+|\d{1,3}(?:,\d{3})+|\d+\.\d+|\d+)(?![\w,]|\.\d)",
    re.IGNORECASE,
)


def derivable_numbers(node, out):
    """Collects every number in the record, along with common renderings.

    Strings in the record are scanned too, because the provenance sentence and
    the host description carry measured values that the report quotes verbatim.
    """
    if isinstance(node, dict):
        for value in node.values():
            derivable_numbers(value, out)
    elif isinstance(node, list):
        for value in node:
            derivable_numbers(value, out)
    elif isinstance(node, bool):
        pass
    elif isinstance(node, str):
        for match in NUMBER.finditer(node):
            out.add(match.group(1).lower())
    elif isinstance(node, (int, float)):
        value = abs(float(node))
        for text in (
            f"{value:.0f}", f"{value:.1f}", f"{value:.2f}", f"{value:.3f}", f"{value:.4f}",
            f"{value:.6f}", f"{value:.0e}", f"{value:.2e}",
        ):
            out.add(text.lower())
        for scaled in (
            value * 100.0, value / 1024.0, value / 1e6, value / 60.0,
            1.0 / value if value else 0.0,
        ):
            for text in (
                f"{scaled:.0f}", f"{scaled:.1f}", f"{scaled:.2f}", f"{scaled:.3f}",
                f"{scaled:.4f}",
            ):
                out.add(text.lower())
        out.add(f"{int(value)}" if float(value).is_integer() else f"{value}")
        if float(value).is_integer():
            out.add(f"{int(value):,}")


def check_report(results, markdown_path, protocol):
    print("\n[3. report.md against results.json]")
    if not os.path.isfile(markdown_path):
        check(False, f"{markdown_path} is present; generate the report first")
        return
    text = open(markdown_path, encoding="utf-8").read()

    # Bibliographic numerals are page ranges and years, not measurements, so the
    # reference list is excluded from the scan.
    scanned = text
    marker = "\n## References"
    if marker in scanned:
        head, _, tail = scanned.partition(marker)
        after = tail.partition("\n## ")
        scanned = head + ("\n## " + after[2] if after[2] else "")

    # Structural text carries numerals that are names and cross-references in
    # place of measurements: section numbers, table and figure numbers, and the
    # name of the floating-point standard. Those are removed before scanning, so
    # the check covers measured values alone.
    scanned = re.sub(r"^#+ .*$", "", scanned, flags=re.MULTILINE)
    scanned = re.sub(r"\b(?:Section|Table|Figure)s?\s+\d+(?:\.\d+)?", "", scanned)
    scanned = scanned.replace("IEEE-754", "")

    known = set()
    derivable_numbers(results, known)
    if protocol:
        derivable_numbers(protocol, known)
    # Small integers and the current year appear in prose and in structure.
    for value in list(range(0, 121)) + [2007, 2017, 2018, 2019, 2022, 2026, 112, 512]:
        known.add(str(value))
        known.add(f"{float(value):.1f}")
        known.add(f"{float(value):.2f}")

    unknown = []
    for match in NUMBER.finditer(scanned):
        token = match.group(1).lower()
        if token in known:
            continue
        # A comma-grouped integer such as 6,000 is written without the comma here.
        if token.replace(",", "") in known:
            continue
        unknown.append(token)

    check(
        not unknown,
        "every number in the report is derivable from the record",
        "unmatched: " + ", ".join(sorted(set(unknown))[:12]) if unknown else "",
    )

    # A handful of headline figures are checked by their exact rendering, so a
    # value that is derivable yet placed in the wrong sentence is still caught.
    accuracy = results["verification_encrypted"]["protocol"]["accuracy_mean"]
    check(
        f"{accuracy * 100:.2f}%" in text,
        "the encrypted accuracy appears in the report as the record states it",
        f"{accuracy * 100:.2f}%",
    )
    flips = results["equivalence"]["observed_flips"]
    check(
        f"count of {flips} changed" in text or f"is {flips}," in text or f"{flips} changed" in text,
        "the count of changed decisions appears in the report",
        str(flips),
    )
    if results["equivalence"]["proved_zero_flips"]:
        check(
            "below one" in text,
            "the report states that the ratio lies below one",
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", default="artifacts/results.json")
    parser.add_argument("--scores", default="artifacts/scores.csv")
    parser.add_argument("--markdown", default="reports/report.md")
    args = parser.parse_args()

    if not os.path.isfile(args.results):
        raise SystemExit(f"{args.results} is absent; run the benchmark first")
    with open(args.results, encoding="utf-8") as handle:
        results = json.load(handle)

    protocol = None
    protocol_path = os.path.join(os.path.dirname(args.results), "session", "protocol.json")
    if os.path.isfile(protocol_path):
        with open(protocol_path, encoding="utf-8") as handle:
            protocol = json.load(handle)

    check_internal(results)
    check_against_scores(results, args.scores)
    check_report(results, args.markdown, protocol)

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} cross-checks passed")
    if FAILURES:
        print(f"{len(FAILURES)} failed:")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
