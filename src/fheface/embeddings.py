"""Pair datasets and face-embedding extraction.

Two dataset sources are supported:

* ``lfw``       : the standard LFW *pairs* benchmark, fetched and cached by
                  scikit-learn (`fetch_lfw_pairs`). Images are already aligned
                  and cropped, so face detection can be skipped -- this removes
                  the single largest source of run-to-run variance.
* ``synthetic`` : deterministic pseudo-embeddings (identity centroid + noise).
                  No deep-learning dependency, no network. Used for smoke tests,
                  CI and for validating the FHE pipeline in isolation.

Two embedding backends are supported:

* ``deepface``  : real face-recognition models (Facenet512, ArcFace, ...).
* ``synthetic`` : the deterministic generator described above.

Every embedding returned by this module is L2-normalised, so that the inner
product computed homomorphically is exactly the cosine similarity.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .utils import l2_normalize, rng

SPLITS = ("train", "test")


# --------------------------------------------------------------------------- #
# Synthetic source
# --------------------------------------------------------------------------- #
def synthetic_pairs(n_pairs: int, dim: int, seed: int, noise: float = 0.7,
                    intrinsic_dim: int = 64,
                    subspace_seed: int = 0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generate balanced (genuine / impostor) pairs of pseudo-embeddings.

    Each identity is a random unit vector; a sample is that centroid plus
    Gaussian noise, re-normalised. The noise is scaled by 1/sqrt(dim) so that the
    intra-identity cosine similarity stays around 1/(1+noise^2) whatever the
    dimension -- otherwise high-dimensional samples would drown in noise. This
    mimics the geometry of real face embeddings closely enough to exercise the
    whole pipeline.

    Identities live in a low-rank subspace (`intrinsic_dim`) that is SHARED by
    the train and test splits, while the identities themselves are disjoint.
    Real face embeddings behave this way, and it is what makes the PCA study
    meaningful: the projection learnt on train transfers to test, and dropping
    the off-subspace directions removes noise instead of signal.
    """
    g = rng(seed)
    gs = rng(subspace_seed)  # split-independent: the manifold is shared
    n_ident = max(2, n_pairs)
    k = min(intrinsic_dim, dim)
    basis = np.linalg.qr(gs.normal(size=(dim, k)))[0].T  # (k, dim), orthonormal
    centroids = l2_normalize(g.normal(size=(n_ident, k)) @ basis)

    sigma = noise / np.sqrt(dim)  # keeps the SNR dimension-independent

    def sample(idx: np.ndarray) -> np.ndarray:
        return l2_normalize(centroids[idx] + sigma * g.normal(size=(idx.size, dim)))

    n_pos = n_pairs // 2
    n_neg = n_pairs - n_pos
    pos_id = g.integers(0, n_ident, size=n_pos)
    x1_pos, x2_pos = sample(pos_id), sample(pos_id)

    a_id = g.integers(0, n_ident, size=n_neg)
    b_id = (a_id + 1 + g.integers(0, n_ident - 1, size=n_neg)) % n_ident  # a != b
    x1_neg, x2_neg = sample(a_id), sample(b_id)

    x1 = np.vstack([x1_pos, x1_neg])
    x2 = np.vstack([x2_pos, x2_neg])
    y = np.concatenate([np.ones(n_pos, dtype=np.int8), np.zeros(n_neg, dtype=np.int8)])
    order = g.permutation(n_pairs)
    return x1[order], x2[order], y[order]


# --------------------------------------------------------------------------- #
# LFW source
# --------------------------------------------------------------------------- #
def load_lfw_pairs(split: str, n_pairs: int | None, seed: int):
    """Fetch LFW pairs via scikit-learn. Returns (images1, images2, labels).

    Images are uint8 RGB arrays. The first call downloads ~200 MB into
    ``~/scikit_learn_data`` and is cached afterwards.
    """
    from sklearn.datasets import fetch_lfw_pairs  # imported lazily: heavy

    subset = "train" if split == "train" else "test"
    data = fetch_lfw_pairs(subset=subset, color=True, resize=1.0, funneled=True)
    pairs = np.clip(data.pairs, 0, 255).astype(np.uint8)  # (n, 2, h, w, 3)
    y = data.target.astype(np.int8)                       # 1 = same identity

    if n_pairs is not None and n_pairs < len(y):
        idx = rng(seed).permutation(len(y))[:n_pairs]
        idx.sort()  # keep a stable, inspectable ordering
        pairs, y = pairs[idx], y[idx]
    return pairs[:, 0], pairs[:, 1], y


# --------------------------------------------------------------------------- #
# DeepFace embedding backend
# --------------------------------------------------------------------------- #
def deepface_embed(images: np.ndarray, model_name: str = "Facenet512") -> np.ndarray:
    """Embed a batch of RGB uint8 images with DeepFace.

    ``detector_backend="skip"`` is intentional: LFW images are already aligned,
    and skipping detection makes results deterministic and much faster.
    """
    from deepface import DeepFace  # imported lazily: heavy (TensorFlow)

    out = []
    for img in images:
        bgr = img[..., ::-1]  # DeepFace/OpenCV expect BGR
        rep = DeepFace.represent(
            img_path=bgr,
            model_name=model_name,
            detector_backend="skip",
            enforce_detection=False,
            align=False,
            normalization="base",
        )
        out.append(np.asarray(rep[0]["embedding"], dtype=np.float64))
    return np.vstack(out)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def build_pair_embeddings(dataset: str, split: str, model: str, n_pairs: int,
                          dim: int, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Return (X1, X2, y, meta) with L2-normalised embeddings."""
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}")

    if dataset == "synthetic" or model == "synthetic":
        # Offset the seed per split so train/test are independent samples.
        s = seed + (0 if split == "train" else 10_000)
        x1, x2, y = synthetic_pairs(n_pairs, dim, s, subspace_seed=seed)
        meta = {"dataset": "synthetic", "model": "synthetic", "dim": int(dim),
                "n_pairs": int(len(y)), "seed": int(s), "split": split}
        return x1, x2, y, meta

    if dataset != "lfw":
        raise ValueError("dataset must be 'lfw' or 'synthetic'")

    img1, img2, y = load_lfw_pairs(split, n_pairs, seed)
    x1 = l2_normalize(deepface_embed(img1, model))
    x2 = l2_normalize(deepface_embed(img2, model))
    meta = {"dataset": "lfw", "model": model, "dim": int(x1.shape[1]),
            "n_pairs": int(len(y)), "seed": int(seed), "split": split}
    return x1, x2, y, meta
