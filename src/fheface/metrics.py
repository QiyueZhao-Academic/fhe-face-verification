"""Verification metrics, implemented with numpy only (no sklearn dependency).

Keeping these self-contained matters for reproducibility: results do not move
when a third-party library changes its interpolation or tie-breaking rules.
"""

from __future__ import annotations

import numpy as np


def cosine_scores(x1: np.ndarray, x2: np.ndarray) -> np.ndarray:
    """Row-wise cosine similarity. Inputs are assumed L2-normalised."""
    return np.sum(x1 * x2, axis=1)


def roc_curve(scores: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (fpr, tpr, thresholds) for a similarity score (higher = same)."""
    order = np.argsort(-scores, kind="mergesort")
    s, y = scores[order], labels[order].astype(np.int64)
    tps = np.cumsum(y)
    fps = np.cumsum(1 - y)
    n_pos = max(int(y.sum()), 1)
    n_neg = max(int((1 - y).sum()), 1)
    # Keep only the last index of each run of equal scores.
    distinct = np.where(np.diff(s))[0]
    idx = np.r_[distinct, s.size - 1]
    tpr = np.r_[0.0, tps[idx] / n_pos]
    fpr = np.r_[0.0, fps[idx] / n_neg]
    thr = np.r_[np.inf, s[idx]]
    return fpr, tpr, thr


def auc(fpr: np.ndarray, tpr: np.ndarray) -> float:
    """Area under the ROC curve (trapezoidal rule)."""
    return float(np.trapezoid(tpr, fpr)) if hasattr(np, "trapezoid") else float(np.trapz(tpr, fpr))


def equal_error_rate(fpr: np.ndarray, tpr: np.ndarray, thr: np.ndarray) -> tuple[float, float]:
    """EER and the threshold at which FPR ~= FNR."""
    fnr = 1.0 - tpr
    i = int(np.nanargmin(np.abs(fnr - fpr)))
    return float((fpr[i] + fnr[i]) / 2.0), float(thr[i])


def best_accuracy(scores: np.ndarray, labels: np.ndarray) -> tuple[float, float]:
    """Highest accuracy over all thresholds, and the threshold reaching it.

    NOTE (methodology): choosing the threshold on the evaluation set is
    optimistic. The report also states accuracy at the threshold selected on the
    *train* split, which is the honest number.
    """
    candidates = np.unique(scores)
    preds = scores[None, :] >= candidates[:, None]
    acc = (preds == labels.astype(bool)[None, :]).mean(axis=1)
    i = int(np.argmax(acc))
    return float(acc[i]), float(candidates[i])


def accuracy_at(scores: np.ndarray, labels: np.ndarray, threshold: float) -> float:
    return float(((scores >= threshold) == labels.astype(bool)).mean())


def summarize(scores: np.ndarray, labels: np.ndarray,
              fixed_threshold: float | None = None) -> dict[str, float]:
    """Standard verification summary for one score vector."""
    fpr, tpr, thr = roc_curve(scores, labels)
    eer, eer_thr = equal_error_rate(fpr, tpr, thr)
    acc, acc_thr = best_accuracy(scores, labels)
    out = {
        "auc": auc(fpr, tpr),
        "eer": eer,
        "eer_threshold": eer_thr,
        "best_accuracy": acc,
        "best_threshold": acc_thr,
        "mean_genuine": float(scores[labels == 1].mean()) if (labels == 1).any() else float("nan"),
        "mean_impostor": float(scores[labels == 0].mean()) if (labels == 0).any() else float("nan"),
    }
    if fixed_threshold is not None:
        out["fixed_threshold"] = float(fixed_threshold)
        out["accuracy_at_fixed_threshold"] = accuracy_at(scores, labels, fixed_threshold)
    return out


def score_error_stats(ref: np.ndarray, approx: np.ndarray) -> dict[str, float]:
    """Numerical agreement between plaintext and homomorphic scores."""
    err = np.abs(np.asarray(approx, dtype=np.float64) - np.asarray(ref, dtype=np.float64))
    return {
        "mae": float(err.mean()),
        "max_abs_error": float(err.max()),
        "rmse": float(np.sqrt((err ** 2).mean())),
    }
