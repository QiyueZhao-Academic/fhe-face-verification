"""Shared helpers: deterministic seeding, paths, timing, IO.

All randomness in this project goes through `rng(seed)` so that every run is
byte-for-byte reproducible on the same machine.
"""

from __future__ import annotations

import json
import os
import platform
import random
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import numpy as np

# Repository root = two levels above this file (src/fheface/utils.py).
ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"
REPORTS = ROOT / "reports"


def ensure_dir(path: str | os.PathLike) -> Path:
    """Create a directory (and parents) if needed and return it."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def set_global_seed(seed: int) -> None:
    """Seed every RNG we may touch, for reproducibility."""
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)


def rng(seed: int) -> np.random.Generator:
    """Return a local, explicitly seeded numpy Generator."""
    return np.random.default_rng(seed)


@contextmanager
def timer() -> Iterator[dict[str, float]]:
    """Context manager measuring wall-clock time in milliseconds.

    Usage:
        with timer() as t:
            do_work()
        print(t["ms"])
    """
    out: dict[str, float] = {}
    t0 = time.perf_counter()
    try:
        yield out
    finally:
        out["ms"] = (time.perf_counter() - t0) * 1000.0


def l2_normalize(x: np.ndarray, axis: int = -1, eps: float = 1e-12) -> np.ndarray:
    """L2-normalise vectors so that a dot product equals a cosine similarity."""
    norm = np.linalg.norm(x, axis=axis, keepdims=True)
    return x / np.maximum(norm, eps)


def save_json(path: str | os.PathLike, obj: Any) -> Path:
    p = Path(path)
    ensure_dir(p.parent)
    p.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    return p


def load_json(path: str | os.PathLike) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_embeddings(path: str | os.PathLike, x1: np.ndarray, x2: np.ndarray,
                    y: np.ndarray, meta: dict[str, Any]) -> Path:
    """Persist a pair dataset: X1[i] and X2[i] form pair i, y[i] in {0,1}."""
    p = Path(path)
    ensure_dir(p.parent)
    np.savez_compressed(p, x1=x1.astype(np.float64), x2=x2.astype(np.float64),
                        y=y.astype(np.int8), meta=json.dumps(meta))
    return p


def load_embeddings(path: str | os.PathLike) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    d = np.load(Path(path), allow_pickle=False)
    meta = json.loads(str(d["meta"]))
    return d["x1"], d["x2"], d["y"], meta


def environment_report() -> dict[str, Any]:
    """Machine/software fingerprint stored next to every result file."""
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "numpy": np.__version__,
    }
