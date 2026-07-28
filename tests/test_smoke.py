"""Fast tests that run without any FHE library or deep-learning dependency.

They pin down the two invariants the whole project relies on:
  1. embeddings are L2-normalised, so a dot product IS the cosine similarity;
  2. every FHE backend reproduces the plaintext score within CKKS noise.
"""

from __future__ import annotations

import numpy as np
import pytest

from fheface import fhe, metrics
from fheface.embeddings import build_pair_embeddings


def test_synthetic_embeddings_are_normalized_and_separable():
    x1, x2, y, meta = build_pair_embeddings("synthetic", "test", "synthetic",
                                            n_pairs=200, dim=64, seed=7)
    assert x1.shape == x2.shape == (200, 64)
    np.testing.assert_allclose(np.linalg.norm(x1, axis=1), 1.0, atol=1e-9)

    s = metrics.cosine_scores(x1, x2)
    assert s[y == 1].mean() > s[y == 0].mean() + 0.3
    assert metrics.summarize(s, y)["auc"] > 0.9


def test_determinism():
    a = build_pair_embeddings("synthetic", "test", "synthetic", 50, 32, 42)[0]
    b = build_pair_embeddings("synthetic", "test", "synthetic", 50, 32, 42)[0]
    np.testing.assert_array_equal(a, b)


def test_metrics_perfect_separation():
    scores = np.array([0.9, 0.8, 0.2, 0.1])
    labels = np.array([1, 1, 0, 0])
    summary = metrics.summarize(scores, labels)
    assert summary["auc"] == pytest.approx(1.0)
    assert summary["eer"] == pytest.approx(0.0)
    assert summary["best_accuracy"] == pytest.approx(1.0)


@pytest.mark.parametrize("backend", list(fhe.AVAILABLE))
def test_backend_matches_plaintext(backend):
    ok, msg = fhe.probe(backend)
    if not ok:
        pytest.skip(f"{backend} unavailable: {msg}")

    x1, x2, _, _ = build_pair_embeddings("synthetic", "test", "synthetic",
                                         n_pairs=4, dim=32, seed=3)
    ref = metrics.cosine_scores(x1, x2)
    got = np.asarray(fhe.get_backend(backend)(x1, x2)["scores"])
    # CKKS is approximate: 1e-3 is several orders above the observed noise.
    np.testing.assert_allclose(got, ref, atol=1e-3)
