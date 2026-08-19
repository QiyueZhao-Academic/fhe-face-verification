#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Turns LFW photographs into the template container the benchmark reads.

Every image referenced by pairs.txt is detected, aligned and embedded exactly
once and then cached in memory, because LFW View 2 names about 7700 distinct
images across its 6000 pairs and embedding each one twice would double the run.

    python3 python/extract_embeddings.py \
        --lfw-root  ~/FHE/ffv-cache/lfw/lfw-deepfunneled \
        --pairs     ~/FHE/ffv-cache/lfw/pairs.txt \
        --models    ~/FHE/ffv-cache/models/buffalo_l \
        --out       artifacts/lfw_templates.ffvemb
"""

import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ffv import face, lfw  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lfw-root", required=True, help="LFW image tree, opened read-only")
    parser.add_argument("--pairs", required=True, help="official pairs.txt")
    parser.add_argument("--models", required=True, help="directory holding the ONNX model pack")
    parser.add_argument("--out", required=True, help="output .ffvemb container")
    parser.add_argument("--limit-pairs", type=int, default=0,
                        help="keep only the first N pairs of each class in each fold")
    parser.add_argument("--detector-size", type=int, default=320,
                        help="square input resolution for the detector (320)")
    parser.add_argument("--threads", type=int, default=0,
                        help="inference threads (0 selects the physical core count)")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--manifest", default="",
                        help="asset manifest, read for the image provenance recorded in the "
                             "container description")
    args = parser.parse_args()

    threads = args.threads if args.threads > 0 else max(1, (os.cpu_count() or 4) // 2)
    lfw_root = os.path.abspath(os.path.expanduser(args.lfw_root))
    if not os.path.isdir(lfw_root):
        raise SystemExit(f"--lfw-root {lfw_root} is not a directory")

    detector_path, recognizer_path = face.find_models(os.path.expanduser(args.models))
    print(f"detector  : {os.path.basename(detector_path)} at {args.detector_size}px")
    print(f"recogniser: {os.path.basename(recognizer_path)}")
    print(f"threads   : {threads}")

    spec, folds = lfw.read_pairs(os.path.expanduser(args.pairs))
    print(f"protocol  : {len(spec)} pairs in {folds} folds")

    # Where the images came from is recorded by the asset stage. Carrying it into
    # the container means the report names the source of its own data.
    provenance = ""
    if args.manifest and os.path.isfile(args.manifest):
        for line in open(args.manifest, encoding="utf-8"):
            if line.startswith("images_provenance "):
                provenance = line.split(" ", 1)[1].strip()
    if provenance:
        print(f"provenance: {provenance}")
    print(f"image tree: {lfw_root}")

    # Keep a balanced prefix when the run is shortened.
    if args.limit_pairs > 0:
        kept, counts = [], {}
        for entry in spec:
            key = (entry[5], entry[4])
            if counts.get(key, 0) < args.limit_pairs:
                counts[key] = counts.get(key, 0) + 1
                kept.append(entry)
        spec = kept
        print(f"protocol  : shortened to {len(spec)} pairs "
              f"({args.limit_pairs} per class per fold)")

    # Resolve every distinct image once.
    wanted, missing = [], []
    index_of = {}
    for name_a, i, name_b, j, _, _ in spec:
        for name, idx in ((name_a, i), (name_b, j)):
            key = (name, idx)
            if key in index_of:
                continue
            path = lfw.image_path(lfw_root, name, idx)
            if path is None:
                missing.append(f"{name}_{idx:04d}.jpg")
                continue
            index_of[key] = len(wanted)
            wanted.append(path)
    if missing:
        present = len(wanted)
        raise SystemExit(
            f"{len(missing)} of the {len(missing) + present} images named by pairs.txt are "
            f"absent from {lfw_root}, starting with {missing[0]}.\n"
            "The protocol file and the image tree describe different datasets. Either the tree "
            "holds a subset of LFW, or it is a different collection. The pair protocol lists "
            "every image it needs by name, so a subset cannot be evaluated against it.\n"
            "Check that the tree holds one subdirectory per identity, each containing files "
            "named like Abel_Pacheco_0001.jpg:\n"
            f"    ls {lfw_root} | head\n"
            f"    ls {lfw_root}/$(ls {lfw_root} | head -1) | head"
        )
    print(f"images    : {len(wanted)} distinct files to embed")

    frontend = face.Frontend(
        detector_path, recognizer_path, size=args.detector_size, threads=threads
    )
    started = time.time()
    vectors = np.zeros((len(wanted), frontend.recognizer.dim))
    for start in range(0, len(wanted), args.batch_size):
        chunk = wanted[start:start + args.batch_size]
        vectors[start:start + len(chunk)] = frontend.embed_paths(chunk, batch_size=len(chunk))
        done = start + len(chunk)
        if done % 800 < args.batch_size or done == len(wanted):
            rate = done / max(1e-9, time.time() - started)
            print(f"  {done}/{len(wanted)} images  ({rate:.1f}/s)", flush=True)
    elapsed = time.time() - started

    dim = vectors.shape[1]
    norm_error = float(np.abs(np.linalg.norm(vectors, axis=1) - 1.0).max())
    detect_rate = frontend.detected / max(1, frontend.detected + frontend.fallback)
    print(f"embedded  : {len(wanted)} images in {elapsed:.1f} s, dimension {dim}")
    print(f"detection : {frontend.detected} found, {frontend.fallback} fell back to the "
          f"central crop ({detect_rate * 100:.2f}% found)")
    print(f"norm error: {norm_error:.3e}")

    pairs = []
    for name_a, i, name_b, j, genuine, fold in spec:
        pairs.append(
            (
                vectors[index_of[(name_a, i)]],
                vectors[index_of[(name_b, j)]],
                genuine,
                fold,
            )
        )

    model_name = os.path.splitext(os.path.basename(recognizer_path))[0]
    description = (
        f"LFW deep-funnelled photographs under the View 2 pair protocol: {len(pairs)} pairs "
        f"in {folds} folds. Faces were located with {os.path.basename(detector_path)} at "
        f"{args.detector_size} pixels, aligned onto the canonical ArcFace five-point template "
        f"by a similarity transform, and embedded by {os.path.basename(recognizer_path)} into "
        f"{dim} dimensions scaled to unit L2 norm. The detector found a face in "
        f"{frontend.detected} of {len(wanted)} images; the remaining {frontend.fallback} used "
        f"the central crop implied by the funnelling registration. The largest deviation of "
        f"any template from unit norm is {norm_error:.3e}."
        + (f" The images came from {provenance}." if provenance else "")
    )
    written = lfw.write_container(
        args.out,
        pairs,
        dim,
        source=f"lfw-{model_name}",
        description=description,
        real_faces=True,
        folds=folds,
    )
    size = os.path.getsize(args.out)
    print(f"wrote     : {args.out} ({written} pairs, {size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
