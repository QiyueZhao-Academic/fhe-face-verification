#!/usr/bin/env python3
"""Report which parts of the pipeline can run on this machine.

Run this first. It never fails hard: it prints a status table so that you know
exactly which backends are usable before launching a long experiment.
"""

from __future__ import annotations

import importlib
import sys

from fheface import fhe
from fheface.utils import environment_report

OPTIONAL_MODULES = [
    ("sklearn", "LFW dataset + PCA"),
    ("matplotlib", "figures for the report"),
    ("deepface", "real face embeddings"),
    ("tensorflow", "DeepFace runtime"),
]


def main() -> int:
    env = environment_report()
    print("== environment ==")
    for k, v in env.items():
        print(f"  {k:10s}: {v}")

    print("\n== optional python packages ==")
    for name, purpose in OPTIONAL_MODULES:
        try:
            mod = importlib.import_module(name)
            version = getattr(mod, "__version__", "?")
            print(f"  [ok]   {name:12s} {version:12s} ({purpose})")
        except Exception as exc:
            print(f"  [--]   {name:12s} {'missing':12s} ({purpose}) -> {type(exc).__name__}")

    print("\n== FHE backends ==")
    usable = []
    for name in fhe.AVAILABLE:
        ok, msg = fhe.probe(name)
        print(f"  [{'ok' if ok else '--'}]   {name:10s} {msg}")
        if ok:
            usable.append(name)

    secure = [b for b in usable if b != "numpy"]
    print("\nUsable backends:", ", ".join(usable) or "none")
    if not secure:
        print("WARNING: no real FHE backend available. Build the SEAL driver "
              "(bash scripts/build_cpp.sh) or install TenSEAL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
