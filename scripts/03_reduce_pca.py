#!/usr/bin/env python3
"""Step 3 -- PCA dimensionality reduction of the templates.

Motivation: CKKS cost is dominated by the number of rotations and by ciphertext
size, both driven by the packing. Shrinking the template from 512 to 64 or 32
dimensions is the cheapest lever available -- provided the accuracy loss is
measured rather than assumed. That measurement is the point of this step.

PCA is fitted on the TRAIN split only, then applied to test. Vectors are
re-normalised after projection so the inner product remains a cosine similarity.
"""

from __future__ import annotations

import argparse

import numpy as np

from fheface import metrics
from fheface.utils import (ARTIFACTS, ensure_dir, l2_normalize, load_embeddings,
                           save_embeddings, save_json)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--emb-dir", default=str(ARTIFACTS / "embeddings"))
    p.add_argument("--dims", type=int, nargs="+", default=[32, 64, 128])
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--out", default=str(ARTIFACTS / "results" / "pca.json"))
    return p.parse_args()


def main() -> None:
    from sklearn.decomposition import PCA  # lazy import: only needed here

    args = parse_args()
    emb_dir = ensure_dir(args.emb_dir)

    x1_tr, x2_tr, y_tr, meta_tr = load_embeddings(emb_dir / "emb_train.npz")
    x1_te, x2_te, y_te, meta_te = load_embeddings(emb_dir / "emb_test.npz")
    full_dim = x1_tr.shape[1]

    # Fit on all train vectors (both sides of every pair).
    train_matrix = np.vstack([x1_tr, x2_tr])

    report = {"full_dim": int(full_dim), "per_dim": {}}
    for dim in sorted(d for d in args.dims if d < full_dim):
        pca = PCA(n_components=dim, random_state=args.seed).fit(train_matrix)

        r1_tr, r2_tr = (l2_normalize(pca.transform(x)) for x in (x1_tr, x2_tr))
        r1_te, r2_te = (l2_normalize(pca.transform(x)) for x in (x1_te, x2_te))

        meta = dict(meta_te, dim=int(dim), reduction="pca", fitted_on="train")
        save_embeddings(emb_dir / f"emb_test_d{dim}.npz", r1_te, r2_te, y_te, meta)
        save_embeddings(emb_dir / f"emb_train_d{dim}.npz", r1_tr, r2_tr, y_tr,
                        dict(meta_tr, dim=int(dim), reduction="pca", fitted_on="train"))

        _, thr = metrics.best_accuracy(metrics.cosine_scores(r1_tr, r2_tr), y_tr)
        summary = metrics.summarize(metrics.cosine_scores(r1_te, r2_te), y_te,
                                    fixed_threshold=thr)
        summary["explained_variance_ratio"] = float(pca.explained_variance_ratio_.sum())
        report["per_dim"][str(dim)] = summary

        print(f"[d={dim:4d}] acc@thr={summary['accuracy_at_fixed_threshold']:.4f} "
              f"AUC={summary['auc']:.4f} EER={summary['eer']:.4f} "
              f"var={summary['explained_variance_ratio']:.3f}")

    print(f"-> {save_json(args.out, report)}")


if __name__ == "__main__":
    main()
