# SPDX-License-Identifier: MIT
"""Figures for the report, drawn from results.json and scores.csv.

Every figure is generated from measured data. A figure whose inputs are absent is
skipped and named in the return value, so the report generator can state plainly
that the run did not produce it.
"""

import csv
import math
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

INK = "#1c1c1c"
GENUINE = "#1f6f43"
IMPOSTOR = "#9c2a2a"
ACCENT = "#1a4f8a"
GREY = "#8a8a8a"

plt.rcParams.update(
    {
        "figure.dpi": 200,
        "savefig.dpi": 200,
        "font.size": 7.5,
        "axes.labelsize": 7.5,
        "axes.titlesize": 8.0,
        "axes.edgecolor": INK,
        "axes.linewidth": 0.6,
        "axes.grid": True,
        "grid.color": "#d8d8d8",
        "grid.linewidth": 0.4,
        "xtick.labelsize": 6.5,
        "ytick.labelsize": 6.5,
        "legend.fontsize": 6.5,
        "legend.frameon": False,
        "lines.linewidth": 1.1,
    }
)


def _save(fig, path):
    fig.tight_layout(pad=0.4)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def read_scores(path):
    """Reads scores.csv into arrays."""
    cleartext, encrypted, labels, folds = [], [], [], []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            cleartext.append(float(row["score_cleartext"]))
            encrypted.append(float(row["score_encrypted"]))
            labels.append(int(row["label"]))
            folds.append(int(row["fold"]))
    return (
        np.array(cleartext),
        np.array(encrypted),
        np.array(labels, dtype=bool),
        np.array(folds),
    )


def figure_pipeline(path):
    """Protocol diagram, drawn to fit one AAAI column.

    A column is 3.3125 inches wide, so the four stages are stacked rather than
    placed side by side and the trust boundary runs horizontally between the two
    halves. The gap that carries the boundary is left wide enough that the arrow
    label, the boundary label and the two region labels each occupy their own
    space.
    """
    fig, ax = plt.subplots(figsize=(3.2, 2.5))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    def box(y, height, title, body, face):
        ax.add_patch(
            plt.Rectangle((6, y), 88, height, facecolor=face, edgecolor=INK, linewidth=0.7,
                          zorder=2)
        )
        ax.text(50, y + height - 5.0, title, ha="center", va="center", fontsize=7.2,
                fontweight="bold", color=INK, zorder=3)
        ax.text(50, y + height / 2 - 3.2, body, ha="center", va="center", fontsize=6.0,
                color=INK, zorder=3)

    def arrow(y_from, y_to, label, label_y):
        ax.annotate(
            "", xy=(50, y_to), xytext=(50, y_from),
            arrowprops=dict(arrowstyle="-|>", color=ACCENT, linewidth=0.9, shrinkA=0, shrinkB=0),
        )
        ax.text(52.5, label_y, label, ha="left", va="center", fontsize=5.9, color=ACCENT,
                zorder=4)

    box(82, 18, "Client", "detect, align, embed\nto a unit-norm vector", "#eef3f9")
    box(58, 18, "Client", "CKKS encrypt under\nthe secret key", "#eef3f9")
    box(20, 18, "Server", "multiply, relinearize,\nrescale, rotate-and-sum", "#f6efe6")
    box(0, 14, "Client", "decrypt score, compare\nto the threshold", "#eef3f9")

    arrow(82, 76.5, "template", 79.2)
    # The long arrow crosses the boundary; its label sits above the line.
    arrow(58, 38.5, "ciphertext", 52.5)
    arrow(20, 14.5, "score ciphertext", 17.2)

    # The trust boundary separates the key holder from the evaluator. Its label
    # and the two region labels sit at opposite edges of the line.
    ax.plot([1, 99], [45, 45], color=GREY, linestyle=(0, (3, 2)), linewidth=0.7, zorder=1)
    ax.text(1, 46.4, "secret key above", ha="left", va="bottom", fontsize=5.9, color=GENUINE)
    ax.text(1, 43.6, "evaluation keys below", ha="left", va="top", fontsize=5.9, color=IMPOSTOR)
    ax.text(99, 46.4, "trust boundary", ha="right", va="bottom", fontsize=5.9, color=GREY)
    return _save(fig, path)


def figure_distributions(path, cleartext, labels, thresholds):
    """Genuine and impostor score histograms with the fold thresholds marked."""
    fig, ax = plt.subplots(figsize=(3.25, 1.85))
    bins = np.linspace(min(cleartext.min(), -0.1), max(cleartext.max(), 1.0), 60)
    ax.hist(cleartext[labels], bins=bins, color=GENUINE, alpha=0.75, label="genuine")
    ax.hist(cleartext[~labels], bins=bins, color=IMPOSTOR, alpha=0.75, label="impostor")
    for i, tau in enumerate(thresholds):
        ax.axvline(tau, color=INK, linewidth=0.5, linestyle=(0, (2, 2)),
                   label="fold thresholds" if i == 0 else None)
    ax.set_xlabel("cosine similarity")
    ax.set_ylabel("pairs")
    ax.legend(loc="upper center")
    return _save(fig, path)


def figure_roc(path, cleartext, labels):
    """Receiver operating characteristic on a logarithmic false accept axis."""
    genuine = np.sort(cleartext[labels])[::-1]
    impostor = np.sort(cleartext[~labels])[::-1]
    n_g, n_i = len(genuine), len(impostor)
    taus = np.unique(np.concatenate([genuine, impostor]))[::-1]
    far = np.array([np.count_nonzero(impostor >= t) / n_i for t in taus])
    tar = np.array([np.count_nonzero(genuine >= t) / n_g for t in taus])
    floor = 1.0 / n_i

    fig, ax = plt.subplots(figsize=(3.25, 1.85))
    keep = far > 0
    ax.semilogx(np.clip(far[keep], floor, 1.0), tar[keep], color=ACCENT)
    ax.set_xlim(floor * 0.8, 1.0)
    # A well-separated system keeps the true accept rate near one across the
    # whole range, so the axis is zoomed onto the region the curve occupies and
    # the shape of the curve stays visible.
    low = float(np.min(tar[keep])) if np.any(keep) else 0.0
    ax.set_ylim(max(0.0, low - 0.02) if low > 0.5 else 0.0, 1.005)

    bottom = ax.get_ylim()[0]
    ax.axvline(floor, color=GREY, linestyle=(0, (2, 2)), linewidth=0.6)
    ax.text(floor * 1.15, bottom + 0.03 * (1.005 - bottom), f"resolution 1/{n_i}",
            fontsize=5.8, color=GREY, rotation=90, va="bottom")
    ax.set_xlabel("false accept rate")
    ax.set_ylabel("true accept rate")
    return _save(fig, path)


def figure_fidelity(path, cleartext, encrypted):
    """Encrypted against cleartext scores, and the histogram of the difference.

    The two panels are stacked so the figure fits a column at its native size,
    which keeps the tick labels legible without downscaling.
    """
    errors = np.abs(encrypted - cleartext)
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(3.25, 2.8))

    top.scatter(cleartext, encrypted - cleartext, s=1.6, color=ACCENT, alpha=0.4,
                edgecolors="none")
    top.axhline(0.0, color=INK, linewidth=0.5)
    top.set_xlabel("cleartext score")
    top.set_ylabel("encrypted minus cleartext")
    top.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))

    positive = errors[errors > 0]
    if positive.size:
        bottom.hist(np.log10(positive), bins=45, color=ACCENT, alpha=0.85)
        bottom.axvline(np.log10(positive.max()), color=IMPOSTOR, linewidth=0.8,
                       label=f"max {positive.max():.2e}")
        bottom.legend(loc="upper left")
    bottom.set_xlabel("log10 absolute error")
    bottom.set_ylabel("pairs")
    return _save(fig, path)


def figure_scale(path, sweep, fit):
    """Measured precision against scale bits, with the slope-1 prediction."""
    usable = [p for p in sweep if p.get("usable") and p.get("precision_bits")]
    if len(usable) < 2:
        return None
    xs = np.array([p["scale_bits"] for p in usable], dtype=float)
    ys = np.array([p["precision_bits"] for p in usable], dtype=float)

    fig, ax = plt.subplots(figsize=(3.25, 1.85))
    ax.plot(xs, ys, "o", color=ACCENT, markersize=3.5, label="measured")
    grid = np.linspace(xs.min() - 1, xs.max() + 1, 50)
    intercept = fit.get("intercept_bits", float(np.mean(ys - xs)))
    ax.plot(grid, grid + intercept, color=IMPOSTOR, linewidth=0.9,
            label=f"slope 1, intercept {intercept:.1f}")
    ax.set_xlabel("scale bits (log2 of $\\Delta$)")
    ax.set_ylabel("precision bits")
    ax.legend(loc="upper left")

    skipped = [p for p in sweep if not p.get("usable")]
    if skipped:
        ax.text(0.98, 0.04, f"{len(skipped)} point(s) rejected", transform=ax.transAxes,
                ha="right", va="bottom", fontsize=5.8, color=GREY)
    return _save(fig, path)


def figure_batching(path, batching):
    """Amortised latency and bandwidth per verification against batch size."""
    if len(batching) < 2:
        return None
    xs = np.array([b["batch"] for b in batching], dtype=float)
    latency = np.array([b["amortised_ms_per_verification"] for b in batching])
    kib = np.array([b["bytes_per_verification"] for b in batching]) / 1024.0

    fig, ax = plt.subplots(figsize=(3.25, 1.85))
    ax.plot(xs, latency, "o-", color=ACCENT, markersize=3.5, label="latency")
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xticks(xs)
    ax.set_xticklabels([str(int(x)) for x in xs])
    ax.set_xlabel("templates packed per ciphertext")
    ax.set_ylabel("ms per verification", color=ACCENT)
    ax.tick_params(axis="y", labelcolor=ACCENT)

    twin = ax.twinx()
    twin.plot(xs, kib, "s--", color=IMPOSTOR, markersize=3.0, label="uplink")
    twin.set_yscale("log")
    twin.set_ylabel("KiB per verification", color=IMPOSTOR)
    twin.tick_params(axis="y", labelcolor=IMPOSTOR)
    twin.grid(False)

    handles = ax.get_lines() + twin.get_lines()
    ax.legend(handles, [h.get_label() for h in handles], loc="lower left")
    return _save(fig, path)


def figure_cost_breakdown(path, cost):
    """Where the server spends the time inside one verification."""
    stages = [
        ("multiply", cost["server_multiply"]["median_ms"]),
        ("relinearize", cost["server_relinearize"]["median_ms"]),
        ("rescale", cost["server_rescale"]["median_ms"]),
        ("rotate-and-sum", cost["server_fold"]["median_ms"]),
    ]
    stages = [(name, value) for name, value in stages if value > 0]
    if not stages:
        return None
    names = [s[0] for s in stages]
    values = [s[1] for s in stages]
    total = sum(values)

    fig, ax = plt.subplots(figsize=(3.25, 1.7))
    positions = np.arange(len(names))
    ax.barh(positions, values, color=ACCENT, height=0.6)
    ax.set_yticks(positions)
    ax.set_yticklabels(names)
    ax.invert_yaxis()
    ax.set_xlabel("median milliseconds")
    for pos, value in zip(positions, values):
        share = 100.0 * value / total if total > 0 else 0.0
        ax.text(value, pos, f"  {value:.2f} ({share:.0f}%)", va="center", fontsize=6.0, color=INK)
    ax.set_xlim(0, max(values) * 1.45)
    ax.grid(axis="y", visible=False)
    return _save(fig, path)


def generate(results, scores_path, out_dir):
    """Writes every figure it can and reports which ones were skipped."""
    os.makedirs(out_dir, exist_ok=True)
    made, skipped = {}, []

    made["pipeline"] = figure_pipeline(os.path.join(out_dir, "fig_pipeline.png"))
    made["circuit"] = figure_circuit(os.path.join(out_dir, "fig_circuit.png"),
                                     results["crypto"], results["circuit_trace"])
    made["slots"] = figure_slots(os.path.join(out_dir, "fig_slots.png"), results["crypto"])

    if os.path.isfile(scores_path):
        cleartext, encrypted, labels, folds = read_scores(scores_path)
        thresholds = [f["threshold"] for f in results["verification_cleartext"]["protocol"]["per_fold"]]
        made["distributions"] = figure_distributions(
            os.path.join(out_dir, "fig_distributions.png"), cleartext, labels, thresholds
        )
        made["roc"] = figure_roc(os.path.join(out_dir, "fig_roc.png"), cleartext, labels)
        made["fidelity"] = figure_fidelity(
            os.path.join(out_dir, "fig_fidelity.png"), cleartext, encrypted
        )
        margin = figure_margin(
            os.path.join(out_dir, "fig_margin.png"), cleartext, folds,
            results["verification_cleartext"]["protocol"]["per_fold"],
            float(results["equivalence"]["max_abs_error"]),
        )
        if margin:
            made["margin"] = margin
        else:
            skipped.append("margin")
    else:
        skipped += ["distributions", "roc", "fidelity", "margin"]

    scale = figure_scale(
        os.path.join(out_dir, "fig_scale.png"),
        results.get("scale_sweep", []),
        results.get("scale_fit", {}),
    )
    if scale:
        made["scale"] = scale
    else:
        skipped.append("scale")

    batching = figure_batching(os.path.join(out_dir, "fig_batching.png"),
                               results.get("batching", []))
    if batching:
        made["batching"] = batching
    else:
        skipped.append("batching")

    breakdown = figure_cost_breakdown(os.path.join(out_dir, "fig_cost.png"),
                                      results["cost_ct_ct"])
    if breakdown:
        made["cost"] = breakdown
    else:
        skipped.append("cost")

    return made, skipped


def figure_circuit(path, crypto, trace):
    """The scoring circuit, with the level and scale at each step.

    The four operations and their effect on the modulus chain are what Section
    3.3 describes in prose; drawing them lets a reader see the single rescale
    that the whole parameter choice is built around.
    """
    scale_bits = int(crypto["scale_bits"])
    primes = list(crypto["coeff_modulus_bits"])
    rotations = int(crypto["rotations_per_score"])
    level_in = int(trace["chain_index_in"])
    level_out = int(trace["chain_index_out"])

    steps = [
        ("encrypt", f"level {level_in}\n$\\Delta = 2^{{{scale_bits}}}$", "#eef3f9"),
        ("multiply", f"level {level_in}\n$\\Delta^2 = 2^{{{2 * scale_bits}}}$", "#f6efe6"),
        ("relinearize", f"level {level_in}\ndegree 3 to 2", "#f6efe6"),
        ("rescale", f"level {level_out}\n$\\Delta = 2^{{{scale_bits}}}$", "#f6efe6"),
        (f"fold, {rotations} rot.", f"level {level_out}\nscore in slot 0", "#f6efe6"),
    ]
    fig, ax = plt.subplots(figsize=(3.25, 1.5))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 46)
    ax.axis("off")
    width, gap = 16.4, 4.4
    for i, (title, body, face) in enumerate(steps):
        x = i * (width + gap)
        ax.add_patch(plt.Rectangle((x, 12), width, 26, facecolor=face, edgecolor=INK,
                                   linewidth=0.6, zorder=2))
        ax.text(x + width / 2, 33.5, title, ha="center", va="center", fontsize=5.6,
                fontweight="bold", color=INK, zorder=3)
        ax.text(x + width / 2, 22, body, ha="center", va="center", fontsize=5.2, color=INK,
                zorder=3)
        if i:
            ax.annotate("", xy=(x - 0.6, 25), xytext=(x - gap + 0.6, 25),
                        arrowprops=dict(arrowstyle="-|>", color=ACCENT, linewidth=0.7,
                                        shrinkA=0, shrinkB=0))
    ax.text(0, 6, f"modulus chain {', '.join(str(p) for p in primes[:-1])} bits, "
                  f"key-switching prime {primes[-1]} bits",
            ha="left", va="center", fontsize=5.2, color=GREY)
    ax.text(0, 43, "multiplicative depth one: the single rescale below is the only level spent",
            ha="left", va="center", fontsize=5.2, color=GREY)
    return _save(fig, path)


def figure_slots(path, crypto):
    """How templates occupy the slots of one ciphertext, before and after the fold."""
    slots = int(crypto["slot_count"])
    block = int(crypto["slots_per_template"])
    batch = int(crypto["max_batch"])

    fig, ax = plt.subplots(figsize=(3.25, 1.45))
    ax.set_xlim(0, slots)
    ax.set_ylim(0, 10)
    ax.axis("off")
    palette = [ACCENT, GENUINE, IMPOSTOR, "#7a5ea8"]
    for k in range(batch):
        x = k * block
        colour = palette[k % len(palette)]
        ax.add_patch(plt.Rectangle((x, 6), block, 3, facecolor=colour, alpha=0.30,
                                   edgecolor=INK, linewidth=0.4))
        ax.add_patch(plt.Rectangle((x, 1.4), block, 3, facecolor="#ffffff", edgecolor=INK,
                                   linewidth=0.4))
        # After the fold the score of each block sits in that block's first slot.
        ax.add_patch(plt.Rectangle((x, 1.4), block * 0.13, 3, facecolor=colour,
                                   edgecolor=INK, linewidth=0.4))
        ax.text(x + block / 2, 7.5, f"{k + 1}", ha="center", va="center", fontsize=5.0,
                color=INK)
    ax.text(0, 9.7, f"before the fold: {batch} templates of {block} slots fill all {slots}",
            ha="left", va="center", fontsize=5.4, color=GREY)
    ax.text(0, 5.1, "after the fold: each block's inner product lands in its first slot",
            ha="left", va="center", fontsize=5.4, color=GREY)
    ax.text(0, 0.3, "slot 0", ha="left", va="center", fontsize=5.0, color=GREY)
    ax.text(slots, 0.3, f"slot {slots - 1}", ha="right", va="center", fontsize=5.0, color=GREY)
    return _save(fig, path)


def figure_margin(path, cleartext, folds, per_fold, max_error):
    """Decision margins against score errors, on one logarithmic axis.

    The bound of the decision-equivalence section is the gap between these two
    distributions, so putting them on one axis makes the argument visible.
    """
    thresholds = {int(f["fold"]): float(f["threshold"]) for f in per_fold}
    margins = np.array([abs(s - thresholds[f]) for s, f in zip(cleartext, folds)
                        if f in thresholds])
    margins = margins[margins > 0]
    if margins.size == 0 or max_error <= 0:
        return None

    fig, ax = plt.subplots(figsize=(3.25, 1.7))
    ax.hist(np.log10(margins), bins=45, color=GENUINE, alpha=0.75,
            label="distance to threshold")
    ax.axvline(np.log10(max_error), color=IMPOSTOR, linewidth=1.0,
               label=f"largest score error {max_error:.2e}")
    smallest = float(margins.min())
    ax.axvline(np.log10(smallest), color=INK, linewidth=0.8, linestyle=(0, (2, 2)),
               label=f"smallest margin {smallest:.2e}")
    ax.set_xlabel("log10 of the distance")
    ax.set_ylabel("pairs")
    ax.legend(loc="upper left", fontsize=5.6)
    ax.set_xlim(min(np.log10(max_error), np.log10(smallest)) - 0.6,
                float(np.log10(margins.max())) + 0.2)
    return _save(fig, path)
