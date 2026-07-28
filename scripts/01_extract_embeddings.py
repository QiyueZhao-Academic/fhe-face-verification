#!/usr/bin/env python3
"""Step 1 -- build and cache L2-normalised pair embeddings.

The train split is used only to fit PCA and to select the decision threshold;
the test split is the one all reported numbers come from.

Examples:
    python scripts/01_extract_embeddings.py --dataset synthetic --n-pairs 400
    python scripts/01_extract_embeddings.py --dataset lfw --model Facenet512 --n-pairs 300
"""

from __future__ import annotations

import argparse

from fheface.embeddings import build_pair_embeddings
from fheface.utils import (ARTIFACTS, ensure_dir, environment_report,
                           save_embeddings, set_global_seed, timer)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=["lfw", "synthetic"], default="synthetic")
    p.add_argument("--model", default="Facenet512",
                   help="DeepFace model name, or 'synthetic'")
    p.add_argument("--n-pairs", type=int, default=300,
                   help="pairs per split (LFW test has 1000, train 2200)")
    p.add_argument("--dim", type=int, default=128,
                   help="dimension of synthetic embeddings (ignored for LFW)")
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--out-dir", default=str(ARTIFACTS / "embeddings"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    set_global_seed(args.seed)
    out_dir = ensure_dir(args.out_dir)

    for split in ("train", "test"):
        with timer() as t:
            x1, x2, y, meta = build_pair_embeddings(
                dataset=args.dataset, split=split, model=args.model,
                n_pairs=args.n_pairs, dim=args.dim, seed=args.seed)
        meta["extraction_ms"] = round(t["ms"], 2)
        meta["env"] = environment_report()
        path = out_dir / f"emb_{split}.npz"
        save_embeddings(path, x1, x2, y, meta)
        print(f"[{split}] {len(y)} pairs, dim={x1.shape[1]}, "
              f"positives={int(y.sum())}, {t['ms']:.0f} ms -> {path}")


if __name__ == "__main__":
    main()
