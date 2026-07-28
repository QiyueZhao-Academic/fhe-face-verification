"""CKKS backend based on TenSEAL (Python bindings over Microsoft SEAL).

Security parameters: poly_modulus_degree N with coefficient-modulus chain
[60, scale_bits, 60]. For N = 8192 the total is 160 bits, well under the
218-bit ceiling for 128-bit security (HomomorphicEncryption.org standard),
so TenSEAL's default 128-bit security level holds.

Multiplicative depth used: 1 (one ciphertext x ciphertext product, then a
rotate-and-sum reduction, which consumes no further multiplicative level).
No bootstrapping is required, which is why this stays fast.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np


def probe() -> tuple[bool, str]:
    try:
        import tenseal as ts
    except Exception as exc:
        return False, f"tenseal not importable ({type(exc).__name__}: {exc})"
    return True, f"tenseal {getattr(ts, '__version__', 'unknown')}"


def _make_context(poly_modulus_degree: int, scale_bits: int):
    import tenseal as ts

    ctx = ts.context(
        ts.SCHEME_TYPE.CKKS,
        poly_modulus_degree=poly_modulus_degree,
        coeff_mod_bit_sizes=[60, scale_bits, 60],
    )
    ctx.global_scale = 2 ** scale_bits
    ctx.generate_galois_keys()  # needed by the rotate-and-sum inside dot()
    ctx.generate_relin_keys()
    return ctx


def run_pairs(a: np.ndarray, b: np.ndarray, poly_modulus_degree: int = 8192,
              scale_bits: int = 40) -> dict[str, Any]:
    import tenseal as ts

    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    n, dim = a.shape

    t0 = time.perf_counter()
    ctx = _make_context(poly_modulus_degree, scale_bits)
    keygen_ms = (time.perf_counter() - t0) * 1000.0

    # --- client side: encrypt both templates -------------------------------
    t0 = time.perf_counter()
    enc_a = [ts.ckks_vector(ctx, a[i].tolist()) for i in range(n)]
    enc_b = [ts.ckks_vector(ctx, b[i].tolist()) for i in range(n)]
    encrypt_ms = (time.perf_counter() - t0) * 1000.0

    ct_size = len(enc_a[0].serialize())

    # --- server side: homomorphic inner product ----------------------------
    t0 = time.perf_counter()
    enc_scores = [enc_a[i].dot(enc_b[i]) for i in range(n)]
    dot_ms = (time.perf_counter() - t0) * 1000.0

    # --- client side: decrypt the score only -------------------------------
    t0 = time.perf_counter()
    scores = [float(s.decrypt()[0]) for s in enc_scores]
    decrypt_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "scores": scores,
        "timings": {
            "keygen_ms": keygen_ms,
            "encrypt_ms_per_vector": encrypt_ms / max(2 * n, 1),
            "dot_ms_per_pair": dot_ms / max(n, 1),
            "decrypt_ms_per_pair": decrypt_ms / max(n, 1),
        },
        "ct_size_bytes": int(ct_size),
        "params": {
            "backend": "tenseal",
            "scheme": "CKKS",
            "poly_modulus_degree": int(poly_modulus_degree),
            "coeff_mod_bit_sizes": [60, int(scale_bits), 60],
            "scale_bits": int(scale_bits),
            "security_level_bits": 128,
            "dim": int(dim),
        },
        "secure": True,
    }
