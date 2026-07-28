#!/usr/bin/env python3
"""Step 2 -- plaintext verification baseline (cosine similarity).

Produces the reference accuracy/EER/AUC that the encrypted pipeline must match,
plus the decision threshold selected on the *train* split (the honest protocol).
"""

from __future__ import annotations

import argparse

from fheface import metrics
from fheface.utils import (ARTIFACTS, REPORTS, ensure_dir, environment_report,
                           load_embeddings, save_json)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--emb-dir", default=str(ARTIFACTS / "embeddings"))
    p.add_argument("--out", default=str(ARTIFACTS / "results" / "baseline.json"))
    p.add_argument("--no-figures", action="store_true")
    return p.parse_args()


def make_figures(scores, labels, out_dir) -> None:
    """ROC curve and genuine/impostor score histograms (optional)."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless: no GUI backend needed
        import matplotlib.pyplot as plt
    except Exception as exc:
        print(f"[figures] skipped ({type(exc).__name__}: {exc})")
        return

    out_dir = ensure_dir(out_dir)
    fpr, tpr, _ = metrics.roc_curve(scores, labels)

    fig, ax = plt.subplots(figsize=(4.5, 4))
    ax.plot(fpr, tpr, lw=2)
    ax.plot([0, 1], [0, 1], "--", lw=0.8, color="grey")
    ax.set_xlabel("False positive rate"); ax.set_ylabel("True positive rate")
    ax.set_title(f"ROC (AUC = {metrics.auc(fpr, tpr):.4f})")
    fig.tight_layout(); fig.savefig(out_dir / "roc_plaintext.png", dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(4.5, 3))
    ax.hist(scores[labels == 1], bins=30, alpha=0.6, label="genuine")
    ax.hist(scores[labels == 0], bins=30, alpha=0.6, label="impostor")
    ax.set_xlabel("cosine similarity"); ax.set_ylabel("count"); ax.legend()
    fig.tight_layout(); fig.savefig(out_dir / "score_distribution.png", dpi=150); plt.close(fig)
    print(f"[figures] written to {out_dir}")


def main() -> None:
    args = parse_args()
    emb_dir = args.emb_dir

    x1_tr, x2_tr, y_tr, meta_tr = load_embeddings(f"{emb_dir}/emb_train.npz")
    x1_te, x2_te, y_te, meta_te = load_embeddings(f"{emb_dir}/emb_test.npz")

    s_tr = metrics.cosine_scores(x1_tr, x2_tr)
    s_te = metrics.cosine_scores(x1_te, x2_te)

    # Threshold chosen on train, applied to test: no evaluation-set leakage.
    _, threshold = metrics.best_accuracy(s_tr, y_tr)
    summary = metrics.summarize(s_te, y_te, fixed_threshold=threshold)

    payload = {
        "train_meta": meta_tr,
        "test_meta": meta_te,
        "threshold_from_train": threshold,
        "test": summary,
        "env": environment_report(),
    }
    path = save_json(args.out, payload)

    print(f"dim                  : {x1_te.shape[1]}")
    print(f"test pairs           : {len(y_te)}")
    print(f"threshold (train)    : {threshold:.4f}")
    print(f"accuracy @ threshold : {summary['accuracy_at_fixed_threshold']:.4f}")
    print(f"best accuracy (test) : {summary['best_accuracy']:.4f}")
    print(f"AUC / EER            : {summary['auc']:.4f} / {summary['eer']:.4f}")
    print(f"-> {path}")

    if not args.no_figures:
        make_figures(s_te, y_te, REPORTS / "figures")


if __name__ == "__main__":
    main()
