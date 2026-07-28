"""CKKS backend driven by the native Microsoft SEAL binary in ``cpp/``.

Rationale: on Apple Silicon the Homebrew package ``seal`` (4.3.x) is a first
class citizen, whereas Python wheels for FHE libraries lag behind. Building the
tiny C++ driver against Homebrew SEAL is therefore the most stable path, and it
also gives realistic timings (no Python interpreter overhead in the crypto).

The Python side only marshals JSON in and out of the binary; the whole
benchmark for a batch runs in a single subprocess call, so process start-up
never pollutes the reported timings.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from ..utils import ROOT

BINARY_ENV = "CKKS_DOT_BIN"
DEFAULT_BINARY = ROOT / "cpp" / "build" / "ckks_dot"


def binary_path() -> Path:
    """Locate the compiled binary (env override, build dir, then PATH)."""
    env = os.environ.get(BINARY_ENV)
    if env:
        return Path(env)
    if DEFAULT_BINARY.exists():
        return DEFAULT_BINARY
    found = shutil.which("ckks_dot")
    return Path(found) if found else DEFAULT_BINARY


def probe() -> tuple[bool, str]:
    p = binary_path()
    if not p.exists():
        return False, f"binary not found at {p} (run: bash scripts/build_cpp.sh)"
    try:
        out = subprocess.run([str(p), "--version"], capture_output=True, text=True,
                             timeout=30, check=True).stdout.strip()
    except Exception as exc:
        return False, f"binary not runnable ({type(exc).__name__}: {exc})"
    return True, out


def run_pairs(a: np.ndarray, b: np.ndarray, poly_modulus_degree: int = 8192,
              scale_bits: int = 40) -> dict[str, Any]:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    binary = binary_path()
    if not binary.exists():
        raise FileNotFoundError(
            f"SEAL driver not built: {binary}. Run `bash scripts/build_cpp.sh` first."
        )

    with tempfile.TemporaryDirectory() as tmp:
        in_path = Path(tmp) / "pairs.json"
        out_path = Path(tmp) / "result.json"
        in_path.write_text(json.dumps({"a": a.tolist(), "b": b.tolist()}), encoding="utf-8")

        cmd = [str(binary), "bench", "--in", str(in_path), "--out", str(out_path),
               "--poly", str(poly_modulus_degree), "--scale-bits", str(scale_bits)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ckks_dot failed ({proc.returncode}): {proc.stderr.strip()}")
        result = json.loads(out_path.read_text(encoding="utf-8"))

    result["params"]["backend"] = "seal_cpp"
    result["params"]["dim"] = int(a.shape[1])
    result["secure"] = True
    return result
