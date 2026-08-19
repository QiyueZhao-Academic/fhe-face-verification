// SPDX-License-Identifier: MIT
//
// Verification metrics for the LFW pair protocol.
//
// Two design rules govern this module.
//
// 1. Every threshold is a midpoint between two adjacent observed scores. A
//    threshold that coincides with a score would leave a pair at zero decision
//    margin, and the decision-equivalence bound in Equivalence would then hold
//    by luck instead of by argument.
//
// 2. Every operating point declares whether the sample can resolve it. A true
//    accept rate quoted at a false accept rate of 1e-3 needs at least one
//    impostor pair per 1e-3 of the sample, so `resolvable` records whether the
//    denominator supports the number and `well_conditioned` records whether it
//    supports it with at least five events.

#ifndef FFV_METRICS_HPP
#define FFV_METRICS_HPP

#include <cstddef>
#include <string>
#include <vector>

namespace ffv {

struct Sample {
    double score = 0.0;
    bool genuine = false;
    int fold = 0;
};

struct Dist {
    int n = 0;
    double mean = 0.0;
    double stddev = 0.0;
    double min = 0.0;
    double max = 0.0;
};

struct FoldResult {
    int fold = 0;
    int n_train = 0;
    int n_test = 0;
    double threshold = 0.0;      // fitted on the other folds only
    double train_accuracy = 0.0;
    double accuracy = 0.0;       // on the held-out fold
    double min_abs_margin = 0.0; // min |score - threshold| over the held-out fold
};

struct Protocol {
    int folds = 0;
    std::vector<FoldResult> per_fold;
    double accuracy_mean = 0.0;
    double accuracy_stddev = 0.0;   // across folds, the figure LFW papers quote
    double accuracy_stderr = 0.0;
    double threshold_mean = 0.0;
    double threshold_stddev = 0.0;
    double min_abs_margin = 0.0;    // smallest margin anywhere in the protocol
};

struct OperatingPoint {
    double target_far = 0.0;
    double achieved_far = 0.0;
    double tar = 0.0;
    double threshold = 0.0;
    int false_accepts = 0;
    bool resolvable = false;        // the impostor count can express target_far
    bool well_conditioned = false;  // at least five false accepts back the estimate
    std::string note;
};

struct Evaluation {
    int n_pairs = 0;
    int n_genuine = 0;
    int n_impostor = 0;
    Dist genuine;
    Dist impostor;
    double d_prime = 0.0;
    double auc = 0.0;
    double eer = 0.0;
    double far_resolution = 0.0; // the smallest non-zero false accept rate expressible
    bool auc_saturated = false;  // an AUC of exactly 1 makes comparisons uninformative
    Protocol protocol;
    std::vector<OperatingPoint> operating_points;
};

// Runs the full evaluation. `folds` comes from the container, so the official
// ten-fold LFW split is honoured when it is present.
Evaluation evaluate(const std::vector<Sample>& samples, const std::vector<double>& target_fars);

// Compares the cleartext and encrypted decisions of one score table.
//
// With E = max |encrypted - cleartext| and M = min |cleartext - threshold|, a
// pair can only cross its threshold when E >= M. Reporting E / M therefore turns
// "no decision changed in this run" into "no decision can change at this noise
// level", which is the claim the report makes.
struct Equivalence {
    int n = 0;
    double max_abs_error = 0.0;
    double mean_abs_error = 0.0;
    double median_abs_error = 0.0;
    double p99_abs_error = 0.0;
    double precision_bits = 0.0; // -log2(max_abs_error)
    double min_abs_margin = 0.0;
    double ratio = 0.0;          // max_abs_error / min_abs_margin
    int observed_flips = 0;
    bool proved_zero_flips = false;
};

Equivalence compare_decisions(const std::vector<Sample>& cleartext,
                              const std::vector<Sample>& encrypted, const Protocol& protocol);

} // namespace ffv

#endif // FFV_METRICS_HPP
