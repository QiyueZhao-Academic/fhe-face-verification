// SPDX-License-Identifier: MIT

#include "ffv/metrics.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <utility>

namespace ffv {

namespace {

Dist describe(const std::vector<double>& xs)
{
    Dist d;
    if (xs.empty()) return d;
    d.n = static_cast<int>(xs.size());
    d.min = *std::min_element(xs.begin(), xs.end());
    d.max = *std::max_element(xs.begin(), xs.end());
    double sum = 0.0;
    for (double x : xs) sum += x;
    d.mean = sum / d.n;
    if (d.n > 1) {
        double acc = 0.0;
        for (double x : xs) acc += (x - d.mean) * (x - d.mean);
        d.stddev = std::sqrt(acc / (d.n - 1));
    }
    return d;
}

// Candidate thresholds: the midpoint of every pair of adjacent distinct scores,
// plus one sentinel below the minimum and one above the maximum. No candidate
// equals an observed score, which is what keeps every decision margin positive.
std::vector<double> midpoint_grid(std::vector<double> scores)
{
    std::sort(scores.begin(), scores.end());
    scores.erase(std::unique(scores.begin(), scores.end()), scores.end());
    std::vector<double> grid;
    if (scores.empty()) return grid;
    const double span = scores.back() - scores.front();
    const double pad = span > 0.0 ? 0.5 * span / static_cast<double>(scores.size()) : 1.0;
    grid.reserve(scores.size() + 1);
    grid.push_back(scores.front() - pad);
    for (std::size_t i = 1; i < scores.size(); ++i) {
        grid.push_back(0.5 * (scores[i - 1] + scores[i]));
    }
    grid.push_back(scores.back() + pad);
    return grid;
}

// A pair is accepted when its score reaches the threshold.
double accuracy_at(const std::vector<Sample>& s, double tau)
{
    if (s.empty()) return 0.0;
    int correct = 0;
    for (const Sample& x : s) {
        const bool accept = x.score >= tau;
        if (accept == x.genuine) ++correct;
    }
    return static_cast<double>(correct) / static_cast<double>(s.size());
}

double min_abs_margin_of(const std::vector<Sample>& s, double tau)
{
    double m = std::numeric_limits<double>::infinity();
    for (const Sample& x : s) m = std::min(m, std::fabs(x.score - tau));
    return std::isfinite(m) ? m : 0.0;
}

// Mann-Whitney U with midranks, which gives the exact area under the ROC curve
// including ties.
double auc_of(const std::vector<double>& genuine, const std::vector<double>& impostor)
{
    const std::size_t ng = genuine.size(), ni = impostor.size();
    if (ng == 0 || ni == 0) return 0.0;
    std::vector<std::pair<double, int>> all; // (score, 1 for genuine)
    all.reserve(ng + ni);
    for (double x : genuine) all.push_back({x, 1});
    for (double x : impostor) all.push_back({x, 0});
    std::sort(all.begin(), all.end(),
              [](const std::pair<double, int>& a, const std::pair<double, int>& b) {
                  return a.first < b.first;
              });
    double rank_sum = 0.0;
    std::size_t i = 0;
    while (i < all.size()) {
        std::size_t j = i;
        while (j + 1 < all.size() && all[j + 1].first == all[i].first) ++j;
        const double midrank = 0.5 * (static_cast<double>(i + 1) + static_cast<double>(j + 1));
        for (std::size_t k = i; k <= j; ++k) {
            if (all[k].second == 1) rank_sum += midrank;
        }
        i = j + 1;
    }
    const double u = rank_sum - 0.5 * static_cast<double>(ng) * static_cast<double>(ng + 1);
    return u / (static_cast<double>(ng) * static_cast<double>(ni));
}

// Equal error rate, found by walking the threshold grid and interpolating
// between the two candidates that bracket the crossing of FAR and FRR.
double eer_of(const std::vector<double>& genuine, const std::vector<double>& impostor)
{
    if (genuine.empty() || impostor.empty()) return 0.0;
    std::vector<double> all(genuine);
    all.insert(all.end(), impostor.begin(), impostor.end());
    const std::vector<double> grid = midpoint_grid(all);
    double best = 1.0, prev_diff = 0.0, prev_far = 0.0, prev_frr = 0.0;
    bool have_prev = false;
    for (double tau : grid) {
        int fa = 0, fr = 0;
        for (double x : impostor) if (x >= tau) ++fa;
        for (double x : genuine) if (x < tau) ++fr;
        const double far = static_cast<double>(fa) / static_cast<double>(impostor.size());
        const double frr = static_cast<double>(fr) / static_cast<double>(genuine.size());
        const double diff = far - frr;
        if (have_prev && ((prev_diff >= 0.0 && diff <= 0.0) || (prev_diff <= 0.0 && diff >= 0.0))) {
            const double denom = prev_diff - diff;
            const double t = std::fabs(denom) > 0.0 ? prev_diff / denom : 0.0;
            const double far_i = prev_far + t * (far - prev_far);
            const double frr_i = prev_frr + t * (frr - prev_frr);
            return 0.5 * (far_i + frr_i);
        }
        best = std::min(best, 0.5 * (far + frr));
        prev_diff = diff;
        prev_far = far;
        prev_frr = frr;
        have_prev = true;
    }
    return best;
}

OperatingPoint tar_at_far(const std::vector<double>& genuine, std::vector<double> impostor,
                          double target)
{
    OperatingPoint op;
    op.target_far = target;
    const std::size_t ni = impostor.size();
    if (ni == 0 || genuine.empty()) {
        op.note = "no pairs of one class, so this point is undefined";
        return op;
    }
    // Largest number of false accepts still within the target rate.
    const int budget = static_cast<int>(std::floor(target * static_cast<double>(ni)));
    op.resolvable = budget >= 1;
    op.well_conditioned = budget >= 5;
    if (!op.resolvable) {
        op.note = "a false accept rate of " + std::to_string(target) + " needs at least "
                  + std::to_string(static_cast<long>(std::ceil(1.0 / target)))
                  + " impostor pairs; this set has " + std::to_string(ni)
                  + ", so no value is reported";
        return op;
    }
    std::sort(impostor.begin(), impostor.end(), std::greater<double>());
    // Accepting at this threshold lets exactly `budget` impostors through when
    // the impostor scores are distinct.
    op.threshold = impostor[static_cast<std::size_t>(budget) - 1];
    int fa = 0;
    for (double x : impostor) if (x >= op.threshold) ++fa;
    op.false_accepts = fa;
    op.achieved_far = static_cast<double>(fa) / static_cast<double>(ni);
    int ta = 0;
    for (double x : genuine) if (x >= op.threshold) ++ta;
    op.tar = static_cast<double>(ta) / static_cast<double>(genuine.size());
    op.note = op.well_conditioned
                  ? "backed by " + std::to_string(fa) + " false accepts"
                  : "backed by only " + std::to_string(fa)
                        + " false accepts, so the estimate is coarse";
    return op;
}

} // namespace

Evaluation evaluate(const std::vector<Sample>& samples, const std::vector<double>& target_fars)
{
    Evaluation ev;
    ev.n_pairs = static_cast<int>(samples.size());
    if (samples.empty()) return ev;

    std::vector<double> g, im;
    int max_fold = 0;
    for (const Sample& s : samples) {
        (s.genuine ? g : im).push_back(s.score);
        max_fold = std::max(max_fold, s.fold);
    }
    ev.n_genuine = static_cast<int>(g.size());
    ev.n_impostor = static_cast<int>(im.size());
    ev.genuine = describe(g);
    ev.impostor = describe(im);
    const double pooled = 0.5 * (ev.genuine.stddev * ev.genuine.stddev
                                 + ev.impostor.stddev * ev.impostor.stddev);
    ev.d_prime = pooled > 0.0 ? (ev.genuine.mean - ev.impostor.mean) / std::sqrt(pooled) : 0.0;
    ev.auc = auc_of(g, im);
    ev.auc_saturated = ev.auc >= 1.0;
    ev.eer = eer_of(g, im);
    ev.far_resolution = ev.n_impostor > 0 ? 1.0 / static_cast<double>(ev.n_impostor) : 0.0;

    // Cross-validated protocol: fit the threshold on every fold but one, then
    // score the held-out fold.
    const int folds = max_fold + 1;
    ev.protocol.folds = folds;
    ev.protocol.min_abs_margin = std::numeric_limits<double>::infinity();
    std::vector<double> accs, taus;
    for (int k = 0; k < folds; ++k) {
        std::vector<Sample> train, test;
        for (const Sample& s : samples) (s.fold == k ? test : train).push_back(s);
        if (test.empty() || train.empty()) continue;
        std::vector<double> train_scores;
        train_scores.reserve(train.size());
        for (const Sample& s : train) train_scores.push_back(s.score);

        FoldResult fr;
        fr.fold = k;
        fr.n_train = static_cast<int>(train.size());
        fr.n_test = static_cast<int>(test.size());
        double best_acc = -1.0, best_tau = 0.0;
        for (double tau : midpoint_grid(train_scores)) {
            const double a = accuracy_at(train, tau);
            if (a > best_acc) { best_acc = a; best_tau = tau; }
        }
        fr.threshold = best_tau;
        fr.train_accuracy = best_acc;
        fr.accuracy = accuracy_at(test, best_tau);
        fr.min_abs_margin = min_abs_margin_of(test, best_tau);
        ev.protocol.min_abs_margin = std::min(ev.protocol.min_abs_margin, fr.min_abs_margin);
        ev.protocol.per_fold.push_back(fr);
        accs.push_back(fr.accuracy);
        taus.push_back(fr.threshold);
    }
    if (!std::isfinite(ev.protocol.min_abs_margin)) ev.protocol.min_abs_margin = 0.0;
    const Dist da = describe(accs), dt = describe(taus);
    ev.protocol.accuracy_mean = da.mean;
    ev.protocol.accuracy_stddev = da.stddev;
    ev.protocol.accuracy_stderr = da.n > 0 ? da.stddev / std::sqrt(static_cast<double>(da.n)) : 0.0;
    ev.protocol.threshold_mean = dt.mean;
    ev.protocol.threshold_stddev = dt.stddev;

    for (double target : target_fars) ev.operating_points.push_back(tar_at_far(g, im, target));
    return ev;
}

Equivalence compare_decisions(const std::vector<Sample>& cleartext,
                              const std::vector<Sample>& encrypted, const Protocol& protocol)
{
    Equivalence eq;
    const std::size_t n = std::min(cleartext.size(), encrypted.size());
    eq.n = static_cast<int>(n);
    if (n == 0) return eq;

    // Fold index -> threshold fitted without that fold.
    std::vector<double> tau_of_fold(static_cast<std::size_t>(protocol.folds) + 1, 0.0);
    std::vector<bool> have(tau_of_fold.size(), false);
    for (const FoldResult& fr : protocol.per_fold) {
        if (fr.fold >= 0 && static_cast<std::size_t>(fr.fold) < tau_of_fold.size()) {
            tau_of_fold[fr.fold] = fr.threshold;
            have[fr.fold] = true;
        }
    }

    std::vector<double> errs(n);
    eq.min_abs_margin = std::numeric_limits<double>::infinity();
    for (std::size_t i = 0; i < n; ++i) {
        errs[i] = std::fabs(encrypted[i].score - cleartext[i].score);
        const int k = cleartext[i].fold;
        if (k < 0 || static_cast<std::size_t>(k) >= have.size() || !have[k]) continue;
        const double tau = tau_of_fold[k];
        eq.min_abs_margin = std::min(eq.min_abs_margin, std::fabs(cleartext[i].score - tau));
        if ((cleartext[i].score >= tau) != (encrypted[i].score >= tau)) ++eq.observed_flips;
    }
    if (!std::isfinite(eq.min_abs_margin)) eq.min_abs_margin = 0.0;

    std::vector<double> sorted(errs);
    std::sort(sorted.begin(), sorted.end());
    eq.max_abs_error = sorted.back();
    double sum = 0.0;
    for (double e : errs) sum += e;
    eq.mean_abs_error = sum / static_cast<double>(n);
    eq.median_abs_error = sorted[n / 2];
    eq.p99_abs_error = sorted[static_cast<std::size_t>(0.99 * static_cast<double>(n - 1))];
    eq.precision_bits = eq.max_abs_error > 0.0 ? -std::log2(eq.max_abs_error) : 0.0;
    eq.ratio = eq.min_abs_margin > 0.0 ? eq.max_abs_error / eq.min_abs_margin
                                       : std::numeric_limits<double>::infinity();
    eq.proved_zero_flips = eq.ratio < 1.0;
    return eq;
}

} // namespace ffv
