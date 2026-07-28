"""Plaintext reference backend.

WARNING: this backend performs NO encryption. It exists so that the benchmark
harness, the metrics and the report can be validated end-to-end without any
cryptographic dependency (useful in CI and on a fresh machine).
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np


def probe() -> tuple[bool, str]:
    return True, "numpy plaintext reference (no encryption)"


def run_pairs(a: np.ndarray, b: np.ndarray, poly_modulus_degree: int = 8192,
              scale_bits: int = 40) -> dict[str, Any]:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)

    t0 = time.perf_counter()
    scores = np.sum(a * b, axis=1)
    dot_ms = (time.perf_counter() - t0) * 1000.0

    n = len(scores)
    return {
        "scores": scores.tolist(),
        "timings": {
            "keygen_ms": 0.0,
            "encrypt_ms_per_vector": 0.0,
            "dot_ms_per_pair": dot_ms / max(n, 1),
            "decrypt_ms_per_pair": 0.0,
        },
        "ct_size_bytes": int(a.shape[1] * 8),  # a plain float64 template
        "params": {"backend": "numpy", "dim": int(a.shape[1])},
        "secure": False,
    }
