# SPDX-License-Identifier: MIT
"""LFW View 2 protocol and the .ffvemb container.

LFW View 2 fixes 6000 pairs in ten folds of 600, each fold holding 300 pairs of
the same person and 300 pairs of different people. Published accuracies are
comparable only when that split is honoured, so the fold index of every pair is
carried into the container and the C++ side cross-validates on it.

The file `pairs.txt` uses two line shapes:

    name  i  j          the i-th and j-th image of `name`      (same person)
    name1 i  name2 j    the i-th image of name1 and the j-th of name2

and its first line gives the fold count and the pairs per class per fold.
"""

import os
import struct

MAGIC = b"FFVEMB03"


def read_pairs(path):
    """Parses pairs.txt into (name_a, index_a, name_b, index_b, genuine, fold)."""
    with open(path, "r", encoding="utf-8") as handle:
        lines = [line.rstrip("\n") for line in handle if line.strip()]
    header = lines[0].split()
    if len(header) != 2:
        raise SystemExit(
            f"{path} does not start with the two-field LFW header 'folds pairs_per_class'"
        )
    folds, per_class = int(header[0]), int(header[1])
    body = lines[1:]
    expected = folds * per_class * 2
    if len(body) != expected:
        raise SystemExit(
            f"{path} declares {folds} folds of {per_class} pairs per class, which is "
            f"{expected} lines, and holds {len(body)}"
        )

    out = []
    for index, line in enumerate(body):
        # Each fold contributes its genuine pairs first, then its impostor pairs.
        fold = index // (2 * per_class)
        fields = line.split()
        if len(fields) == 3:
            out.append((fields[0], int(fields[1]), fields[0], int(fields[2]), True, fold))
        elif len(fields) == 4:
            out.append((fields[0], int(fields[1]), fields[2], int(fields[3]), False, fold))
        else:
            raise SystemExit(f"{path} line {index + 2} has {len(fields)} fields, expected 3 or 4")
    return out, folds


def image_path(root, name, index):
    """Resolves one LFW image, accepting a flat or per-person directory layout."""
    filename = f"{name}_{index:04d}.jpg"
    for candidate in (os.path.join(root, name, filename), os.path.join(root, filename)):
        if os.path.isfile(candidate):
            return candidate
    return None


def write_container(path, pairs, dim, source, description, real_faces, folds):
    """Writes the .ffvemb container the C++ benchmark reads.

    `pairs` is a sequence of (vector_a, vector_b, genuine, fold). Vectors are
    stored as float32, which holds more precision than the CKKS circuit resolves
    and halves the file against float64.
    """
    source_bytes = source.encode("utf-8")
    description_bytes = description.encode("utf-8")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(MAGIC)
        handle.write(
            struct.pack(
                "<6I",
                dim,
                len(pairs),
                folds,
                1 if real_faces else 0,
                len(source_bytes),
                len(description_bytes),
            )
        )
        handle.write(source_bytes)
        handle.write(description_bytes)
        for vector_a, vector_b, genuine, fold in pairs:
            handle.write(vector_a.astype("<f4").tobytes())
            handle.write(vector_b.astype("<f4").tobytes())
            handle.write(struct.pack("<BHB", 1 if genuine else 0, fold, 0))
    return len(pairs)


def read_header(path):
    """Reads a container header, for inspection without loading the vectors."""
    with open(path, "rb") as handle:
        if handle.read(8) != MAGIC:
            raise SystemExit(f"{path} is not an FFVEMB03 container")
        dim, count, folds, flags, len_source, len_desc = struct.unpack("<6I", handle.read(24))
        source = handle.read(len_source).decode("utf-8", "replace")
        description = handle.read(len_desc).decode("utf-8", "replace")
    return {
        "dim": dim,
        "pairs": count,
        "folds": folds,
        "real_faces": bool(flags & 1),
        "source": source,
        "description": description,
    }
