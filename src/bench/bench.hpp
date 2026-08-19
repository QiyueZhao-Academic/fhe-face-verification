// SPDX-License-Identifier: MIT
//
// Declarations shared by the benchmark translation units.
//
// The layout mirrors the report: one file computes the encrypted score table,
// one derives the verification metrics from it, three measure cost, and one
// serialises everything. Keeping the JSON emitter alone in charge of output
// removes the possibility of two files disagreeing about a number.

#ifndef FFV_BENCH_HPP
#define FFV_BENCH_HPP

#include <cstddef>
#include <string>
#include <vector>

#include "ffv/client.hpp"
#include "ffv/crypto.hpp"
#include "ffv/metrics.hpp"
#include "ffv/platform.hpp"
#include "ffv/server.hpp"
#include "ffv/templates.hpp"
#include "ffv/timing.hpp"

namespace ffv {
namespace bench {

struct Options {
    std::string templates_path;
    std::string out_dir = "artifacts";
    std::string out_json = "artifacts/results.json";
    std::string out_scores = "artifacts/scores.csv";
    int pairs = 0;              // 0 evaluates every pair in the container
    Params params;
    Fold fold = Fold::Log2;
    Mode mode = Mode::CtCt;     // circuit used for the score table
    int score_batch = 0;        // 0 selects the largest batch the slots allow
    int cost_reps = 20;
    int naive_reps = 3;
    int scale_pairs = 64;
    std::vector<int> scale_bits_sweep;
    std::vector<int> batch_sweep;
    std::vector<double> target_fars;
    bool skip_naive = false;
    bool skip_scale = false;

    static Options defaults();
};

bool parse_options(int argc, char** argv, Options& opt, std::string& error);
std::string usage();

// ---------------------------------------------------------------------------
// Experiment outputs
// ---------------------------------------------------------------------------

struct ScoreTable {
    std::vector<Sample> cleartext;
    std::vector<Sample> encrypted;
    int batch = 1;
    int calls = 0;              // homomorphic score operations performed
    double ms_encrypt_total = 0.0;
    double ms_server_total = 0.0;
    double ms_decrypt_total = 0.0;
    double ms_wall_total = 0.0;
    Trace trace;                // one representative call
};

struct CostResult {
    Mode mode = Mode::CtCt;
    Fold fold = Fold::Log2;
    int rotations = 0;
    Stat encrypt_ms;
    Stat server_ms;
    Stat decrypt_ms;
    Stat multiply_ms;
    Stat relinearize_ms;
    Stat rescale_ms;
    Stat fold_ms;
    Bytes fresh_ciphertext;     // one encrypted template, the uplink unit
    Bytes result_ciphertext;    // the returned score, the downlink unit
    double uplink_bytes_per_verification = 0.0;
    double downlink_bytes_per_verification = 0.0;
    double max_abs_error = 0.0; // over the repetitions used for timing
};

struct BatchPoint {
    int batch = 1;
    Stat server_ms;
    double amortised_ms = 0.0;
    Bytes ciphertext;
    double bytes_per_verification = 0.0;
    double max_abs_error = 0.0;
    double throughput_per_second = 0.0;
};

struct ScalePoint {
    int scale_bits = 0;
    int last_prime_bits = 0;
    int headroom_bits = 0;      // last_prime_bits - scale_bits
    int total_coeff_bits = 0;
    bool usable = false;
    std::string note;
    double max_abs_error = 0.0;
    double precision_bits = 0.0;
    double server_ms = 0.0;
};

// Slope of measured precision against scale bits.
//
// Rescaling divides the ciphertext noise by the scaling factor, so one extra
// scale bit buys exactly one precision bit and the predicted slope is 1 with no
// constant to tune. The intercept is the circuit's noise floor and is reported
// as a measurement.
struct ScaleFit {
    int points_used = 0;
    double measured_slope = 0.0;
    double predicted_slope = 1.0;
    double slope_deviation = 0.0;
    double intercept_bits = 0.0;
    double max_residual_bits = 0.0;
    double r_squared = 0.0;
};

struct Results {
    Platform platform;
    Options options;
    ParamCheck check;
    std::vector<LevelInfo> chain;
    std::size_t slot_count = 0;
    std::size_t block = 0;
    std::size_t max_batch = 0;

    TemplateSet meta;           // pairs cleared after loading to keep this small
    int n_pairs_used = 0;

    KeySizes keys;
    double keygen_ms = 0.0;

    ScoreTable scores;
    Evaluation eval_cleartext;
    Evaluation eval_encrypted;
    Equivalence equivalence;

    CostResult cost_ct_ct;
    CostResult cost_ct_pt;
    bool have_naive = false;
    CostResult cost_naive;

    std::vector<BatchPoint> batching;
    std::vector<ScalePoint> scale;
    ScaleFit scale_fit;

    double total_wall_seconds = 0.0;
};

// Each of these returns false and fills `error` on failure.
bool compute_scores(const Options& opt, const TemplateSet& set, Client& client, Server& server,
                    ScoreTable& out, std::string& error);
bool measure_cost(const Options& opt, const TemplateSet& set, Results& res, std::string& error);
bool measure_batching(const Options& opt, const TemplateSet& set, Results& res,
                      std::string& error);
bool measure_scale(const Options& opt, const TemplateSet& set, Results& res, std::string& error);

ScaleFit fit_scale(const std::vector<ScalePoint>& points);

bool write_json(const Results& res, const std::string& path, std::string& error);
bool write_scores_csv(const ScoreTable& t, const std::string& path, std::string& error);

int run(int argc, char** argv);

} // namespace bench
} // namespace ffv

#endif // FFV_BENCH_HPP
