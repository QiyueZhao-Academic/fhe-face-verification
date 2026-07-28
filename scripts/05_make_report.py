#!/usr/bin/env python3
"""Step 5 -- assemble every JSON artifact into reports/results.md.

The output is meant to be pasted (tables and all) into the technical report.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from fheface.utils import ARTIFACTS, REPORTS, ensure_dir, load_json


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results-dir", default=str(ARTIFACTS / "results"))
    p.add_argument("--out", default=str(REPORTS / "results.md"))
    return p.parse_args()


def table(headers: list[str], rows: list[list[str]]) -> str:
    line = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join("---" for _ in headers) + "|"
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return "\n".join([line, sep, body])


def main() -> None:
    args = parse_args()
    results_dir = Path(args.results_dir)
    parts: list[str] = [
        "# Experimental results",
        "",
        f"Generated: {dt.datetime.now().isoformat(timespec='seconds')}",
        "",
    ]

    baseline_path = results_dir / "baseline.json"
    if baseline_path.exists():
        b = load_json(baseline_path)
        m, meta = b["test"], b["test_meta"]
        parts += [
            "## 1. Plaintext baseline",
            "",
            f"Dataset `{meta['dataset']}`, model `{meta['model']}`, "
            f"dim {meta['dim']}, {meta['n_pairs']} test pairs. "
            f"Threshold selected on the train split: {b['threshold_from_train']:.4f}.",
            "",
            table(["metric", "value"], [
                ["accuracy @ train threshold", f"{m['accuracy_at_fixed_threshold']:.4f}"],
                ["best accuracy (test)", f"{m['best_accuracy']:.4f}"],
                ["AUC", f"{m['auc']:.4f}"],
                ["EER", f"{m['eer']:.4f}"],
                ["mean genuine / impostor score",
                 f"{m['mean_genuine']:.3f} / {m['mean_impostor']:.3f}"],
            ]),
            "",
        ]

    pca_path = results_dir / "pca.json"
    if pca_path.exists():
        p = load_json(pca_path)
        rows = [[d, f"{v['accuracy_at_fixed_threshold']:.4f}", f"{v['auc']:.4f}",
                 f"{v['eer']:.4f}", f"{v['explained_variance_ratio']:.3f}"]
                for d, v in sorted(p["per_dim"].items(), key=lambda kv: int(kv[0]))]
        parts += [
            "## 2. Effect of PCA dimensionality reduction",
            "",
            f"PCA fitted on the train split. Full dimension: {p['full_dim']}.",
            "",
            table(["dim", "accuracy", "AUC", "EER", "explained var."], rows),
            "",
        ]

    fhe_files = sorted(results_dir.glob("fhe_*.json"))
    if fhe_files:
        rows = []
        for f in fhe_files:
            r = load_json(f)
            t, e = r["timings_ms"], r["score_error"]
            rows.append([
                r["backend"],
                str(r["params"].get("dim", r["dim_label"])),
                "yes" if r["secure"] else "NO",
                f"{r['encrypted_metrics']['best_accuracy']:.4f}",
                f"{r['plaintext_metrics']['best_accuracy']:.4f}",
                f"{e['max_abs_error']:.2e}",
                f"{t['encrypt_ms_per_vector']:.1f}",
                f"{t['dot_ms_per_pair']:.1f}",
                f"{t['decrypt_ms_per_pair']:.1f}",
                f"{r['ct_size_bytes'] / 1024:.0f}",
            ])
        parts += [
            "## 3. Encrypted matching (CKKS)",
            "",
            table(["backend", "dim", "encrypted", "acc (enc)", "acc (plain)",
                   "max abs err", "encrypt ms/vec", "dot ms/pair", "decrypt ms/pair",
                   "ct KiB"], rows),
            "",
            "`encrypted = NO` marks the plaintext reference backend, kept only "
            "as a correctness and speed baseline.",
            "",
        ]

        first = load_json(fhe_files[0])["params"]
        parts += [
            "### Parameters",
            "",
            "```json",
            "\n".join(f"{k}: {v}" for k, v in first.items()),
            "```",
            "",
        ]

    figures = sorted((REPORTS / "figures").glob("*.png"))
    if figures:
        parts += ["## 4. Figures", ""]
        parts += [f"![{f.stem}](figures/{f.name})" for f in figures] + [""]

    out = ensure_dir(Path(args.out).parent) / Path(args.out).name
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
