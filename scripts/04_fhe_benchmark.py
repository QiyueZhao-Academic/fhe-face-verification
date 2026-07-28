#!/usr/bin/env python3
"""Step 4 -- encrypted matching benchmark.

For each (backend, dimension) it measures:
  * accuracy / AUC / EER obtained from the DECRYPTED scores,
  * numerical agreement with the plaintext scores (CKKS is approximate),
  * key generation, encryption, homomorphic dot product and decryption times,
  * ciphertext size.

Only the similarity score is ever decrypted; templates stay encrypted end to end.

Example:
    python scripts/04_fhe_benchmark.py --backends seal_cpp numpy --dims full 64 32
"""

from __future__ import annotations

import argparse

import numpy as np

from fheface import fhe, metrics
from fheface.utils import (ARTIFACTS, ensure_dir, environment_report,
                           load_embeddings, save_json)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--emb-dir", default=str(ARTIFACTS / "embeddings"))
    p.add_argument("--backends", nargs="+", default=["numpy"],
                   choices=list(fhe.AVAILABLE))
    p.add_argument("--dims", nargs="+", default=["full"],
                   help="'full' for the untouched embeddings, or PCA dims like 64 32")
    p.add_argument("--n-pairs", type=int, default=100,
                   help="cap on evaluated pairs (FHE is slow; keep it explicit)")
    p.add_argument("--poly", type=int, default=8192, help="poly_modulus_degree")
    p.add_argument("--scale-bits", type=int, default=40)
    p.add_argument("--out-dir", default=str(ARTIFACTS / "results"))
    return p.parse_args()


def load_split(emb_dir: str, dim: str):
    suffix = "" if dim == "full" else f"_d{dim}"
    return load_embeddings(f"{emb_dir}/emb_test{suffix}.npz")


def main() -> None:
    args = parse_args()
    out_dir = ensure_dir(args.out_dir)

    for dim in args.dims:
        x1, x2, y, meta = load_split(args.emb_dir, dim)
        n = min(args.n_pairs, len(y))
        x1, x2, y = x1[:n], x2[:n], y[:n]
        ref = metrics.cosine_scores(x1, x2)

        for backend in args.backends:
            ok, msg = fhe.probe(backend)
            if not ok:
                print(f"[skip] backend {backend}: {msg}")
                continue

            run = fhe.get_backend(backend)
            result = run(x1, x2, poly_modulus_degree=args.poly,
                         scale_bits=args.scale_bits)
            scores = np.asarray(result["scores"], dtype=np.float64)

            payload = {
                "backend": backend,
                "dim_label": dim,
                "n_pairs": int(n),
                "embedding_meta": meta,
                "params": result["params"],
                "secure": result["secure"],
                "timings_ms": result["timings"],
                "ct_size_bytes": result["ct_size_bytes"],
                "galois_keys_bytes": result.get("galois_keys_bytes"),
                "encrypted_metrics": metrics.summarize(scores, y),
                "plaintext_metrics": metrics.summarize(ref, y),
                "score_error": metrics.score_error_stats(ref, scores),
                "env": environment_report(),
            }
            path = save_json(out_dir / f"fhe_{backend}_d{dim}.json", payload)

            t = result["timings"]
            e = payload["score_error"]
            print(f"[{backend:8s} d={dim:>4s}] "
                  f"acc={payload['encrypted_metrics']['best_accuracy']:.4f} "
                  f"max|err|={e['max_abs_error']:.2e} "
                  f"enc={t['encrypt_ms_per_vector']:.1f}ms/vec "
                  f"dot={t['dot_ms_per_pair']:.1f}ms/pair "
                  f"dec={t['decrypt_ms_per_pair']:.1f}ms/pair "
                  f"ct={result['ct_size_bytes'] / 1024:.0f}KiB -> {path.name}")


if __name__ == "__main__":
    main()
