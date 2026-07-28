"""Pluggable CKKS backends.

Every backend exposes the same function::

    run_pairs(A, B, poly_modulus_degree, scale_bits) -> dict

with the returned dictionary containing:
    scores          : list[float]  -- decrypted similarity, one per pair
    timings         : dict[str, float] (milliseconds)
    ct_size_bytes   : int          -- serialised size of one ciphertext
    params          : dict         -- parameters actually used
    secure          : bool         -- False for the plaintext reference backend

Backends:
    numpy    : plaintext reference. NOT encryption. Used to validate the harness.
    tenseal  : TenSEAL (SEAL bindings for Python). Easiest to install.
    seal_cpp : native Microsoft SEAL binary built from ``cpp/``. Most reliable on
               Apple Silicon, since it links against the Homebrew SEAL package.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Callable

AVAILABLE = ("numpy", "tenseal", "seal_cpp")


def get_backend(name: str) -> Callable[..., dict[str, Any]]:
    """Return the ``run_pairs`` callable of a backend, or raise ImportError."""
    if name not in AVAILABLE:
        raise ValueError(f"unknown backend {name!r}, expected one of {AVAILABLE}")
    mod = import_module(f"fheface.fhe.{name}_backend")
    return mod.run_pairs


def probe(name: str) -> tuple[bool, str]:
    """Check whether a backend can run here. Returns (ok, message)."""
    try:
        mod = import_module(f"fheface.fhe.{name}_backend")
        return mod.probe()
    except Exception as exc:  # pragma: no cover - diagnostics path
        return False, f"{type(exc).__name__}: {exc}"
