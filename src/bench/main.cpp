// SPDX-License-Identifier: MIT
//
// Benchmark orchestrator: parse options, load templates, run the experiments in
// order, write one JSON file.

#include "bench.hpp"

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <sstream>

#include "ffv/io.hpp"

namespace ffv {
namespace bench {

namespace {

std::vector<int> parse_int_list(const std::string& text)
{
    std::vector<int> out;
    std::stringstream ss(text);
    std::string tok;
    while (std::getline(ss, tok, ',')) {
        if (!tok.empty()) out.push_back(std::atoi(tok.c_str()));
    }
    return out;
}

std::vector<double> parse_double_list(const std::string& text)
{
    std::vector<double> out;
    std::stringstream ss(text);
    std::string tok;
    while (std::getline(ss, tok, ',')) {
        if (!tok.empty()) out.push_back(std::atof(tok.c_str()));
    }
    return out;
}

bool need_value(int argc, char** argv, int& i, const char* flag, std::string& value,
                std::string& error)
{
    if (i + 1 >= argc) {
        error = std::string(flag) + " needs a value";
        return false;
    }
    value = argv[++i];
    return true;
}

} // namespace

Options Options::defaults()
{
    Options o;
    o.scale_bits_sweep = {25, 30, 35, 40, 45, 50};
    o.batch_sweep = {1, 2, 4, 8};
    // 1e-2 is resolvable by a few hundred impostor pairs; 1e-3 needs a thousand;
    // 1e-4 is listed so the report states plainly that LFW cannot resolve it.
    o.target_fars = {1e-2, 1e-3, 1e-4};
    return o;
}

std::string usage()
{
    return
        "ffv_bench --templates FILE [options]\n"
        "\n"
        "  --templates FILE     .ffvemb container written by extract_embeddings.py\n"
        "  --out-dir DIR        directory for results.json and scores.csv (artifacts)\n"
        "  --pairs N            evaluate the first N pairs of each fold (0 = all)\n"
        "  --degree N           poly_modulus_degree (8192)\n"
        "  --scale-bits N       log2 of the CKKS scaling factor (40)\n"
        "  --last-prime-bits N  width of the prime that survives the rescale (60)\n"
        "  --mode ct_ct|ct_pt   circuit used for the score table (ct_ct)\n"
        "  --fold log2|naive    rotate-and-sum strategy (log2)\n"
        "  --score-batch N      templates packed per ciphertext (0 = as many as fit)\n"
        "  --cost-reps N        repetitions per timed operation (20)\n"
        "  --naive-reps N       repetitions for the d-1 rotation baseline (3)\n"
        "  --scale-pairs N      pairs used at each point of the scale sweep (64)\n"
        "  --scale-sweep LIST   comma-separated scale_bits values\n"
        "  --batch-sweep LIST   comma-separated batch sizes\n"
        "  --target-fars LIST   comma-separated false accept rates\n"
        "  --skip-naive         omit the d-1 rotation cost baseline\n"
        "  --skip-scale         omit the scale sweep\n";
}

bool parse_options(int argc, char** argv, Options& opt, std::string& error)
{
    opt = Options::defaults();
    std::string v;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (a == "--templates") {
            if (!need_value(argc, argv, i, "--templates", v, error)) return false;
            opt.templates_path = v;
        } else if (a == "--out-dir") {
            if (!need_value(argc, argv, i, "--out-dir", v, error)) return false;
            opt.out_dir = v;
        } else if (a == "--pairs") {
            if (!need_value(argc, argv, i, "--pairs", v, error)) return false;
            opt.pairs = std::atoi(v.c_str());
        } else if (a == "--degree") {
            if (!need_value(argc, argv, i, "--degree", v, error)) return false;
            opt.params.poly_modulus_degree = static_cast<std::size_t>(std::atol(v.c_str()));
        } else if (a == "--scale-bits") {
            if (!need_value(argc, argv, i, "--scale-bits", v, error)) return false;
            opt.params.scale_bits = std::atoi(v.c_str());
        } else if (a == "--last-prime-bits") {
            if (!need_value(argc, argv, i, "--last-prime-bits", v, error)) return false;
            opt.params.last_prime_bits = std::atoi(v.c_str());
        } else if (a == "--mode") {
            if (!need_value(argc, argv, i, "--mode", v, error)) return false;
            if (!parse_mode(v, opt.mode)) {
                error = "--mode accepts ct_ct or ct_pt; got " + v;
                return false;
            }
        } else if (a == "--fold") {
            if (!need_value(argc, argv, i, "--fold", v, error)) return false;
            if (!parse_fold(v, opt.fold)) {
                error = "--fold accepts log2 or naive; got " + v;
                return false;
            }
        } else if (a == "--score-batch") {
            if (!need_value(argc, argv, i, "--score-batch", v, error)) return false;
            opt.score_batch = std::atoi(v.c_str());
        } else if (a == "--naive-reps") {
            if (!need_value(argc, argv, i, "--naive-reps", v, error)) return false;
            opt.naive_reps = std::atoi(v.c_str());
        } else if (a == "--scale-pairs") {
            if (!need_value(argc, argv, i, "--scale-pairs", v, error)) return false;
            opt.scale_pairs = std::atoi(v.c_str());
        } else if (a == "--cost-reps") {
            if (!need_value(argc, argv, i, "--cost-reps", v, error)) return false;
            opt.cost_reps = std::atoi(v.c_str());
        } else if (a == "--scale-sweep") {
            if (!need_value(argc, argv, i, "--scale-sweep", v, error)) return false;
            opt.scale_bits_sweep = parse_int_list(v);
        } else if (a == "--batch-sweep") {
            if (!need_value(argc, argv, i, "--batch-sweep", v, error)) return false;
            opt.batch_sweep = parse_int_list(v);
        } else if (a == "--target-fars") {
            if (!need_value(argc, argv, i, "--target-fars", v, error)) return false;
            opt.target_fars = parse_double_list(v);
        } else if (a == "--skip-naive") {
            opt.skip_naive = true;
        } else if (a == "--skip-scale") {
            opt.skip_scale = true;
        } else if (a == "-h" || a == "--help") {
            std::cout << usage();
            std::exit(0);
        } else {
            error = "unknown option " + a + "\n\n" + usage();
            return false;
        }
    }
    if (opt.templates_path.empty()) {
        error = "--templates is required\n\n" + usage();
        return false;
    }
    if (opt.cost_reps < 1) {
        error = "--cost-reps must be at least 1";
        return false;
    }
    opt.out_json = join(opt.out_dir, "results.json");
    opt.out_scores = join(opt.out_dir, "scores.csv");
    return true;
}

namespace {

// Keeps the first `per_fold` pairs of each class in each fold, so a shortened
// run stays balanced and keeps every fold populated.
TemplateSet subsample(const TemplateSet& set, int limit)
{
    if (limit <= 0 || limit >= static_cast<int>(set.pairs.size())) return set;
    TemplateSet out = set;
    out.pairs.clear();
    const int folds = set.folds > 0 ? set.folds : 1;
    const int per_class = std::max(1, limit / (2 * folds));
    std::vector<int> taken_g(folds, 0), taken_i(folds, 0);
    for (const Pair& p : set.pairs) {
        const int f = p.fold >= 0 && p.fold < folds ? p.fold : 0;
        int& taken = p.genuine ? taken_g[f] : taken_i[f];
        if (taken < per_class) {
            out.pairs.push_back(p);
            ++taken;
        }
    }
    out.description = set.description + " Subsampled to the first " + std::to_string(per_class)
                      + " genuine and " + std::to_string(per_class)
                      + " impostor pairs of each fold.";
    return out;
}

void report(const char* stage) { std::cout << "  " << stage << std::endl; }

} // namespace

int run(int argc, char** argv)
{
    Options opt;
    std::string error;
    if (!parse_options(argc, argv, opt, error)) {
        std::cerr << "ffv_bench: " << error << "\n";
        return 2;
    }
    const Timer wall;

    Results res;
    res.platform = describe_platform();
    std::cout << "host   : " << res.platform.os << " " << res.platform.os_version << " "
              << res.platform.arch << ", " << res.platform.cpu << "\n"
              << "build  : " << res.platform.compiler << " " << res.platform.build_type
              << ", SEAL " << res.platform.seal_version << "\n";
    if (res.platform.translated) {
        std::cerr << "ffv_bench: refusing to publish timings measured under Rosetta 2; "
                     "rebuild natively for arm64\n";
        return 3;
    }

    TemplateSet set;
    if (!load_templates(opt.templates_path, set, error)) {
        std::cerr << "ffv_bench: " << error << "\n";
        return 4;
    }
    if (set.dim != opt.params.dim) opt.params.dim = set.dim;
    set = subsample(set, opt.pairs);
    std::cout << "pairs  : " << set.size() << " (" << set.genuine_count() << " genuine, "
              << set.impostor_count() << " impostor) in " << set.folds << " folds, dim "
              << set.dim << "\n"
              << "source : " << set.source << (set.real_faces ? " [photographs]" : " [synthetic]")
              << "\n";

    res.options = opt;
    res.check = check_params(opt.params);
    if (!res.check.ok) {
        std::cerr << "ffv_bench: " << res.check.message << "\n";
        return 5;
    }
    res.n_pairs_used = static_cast<int>(set.size());
    res.slot_count = opt.params.slot_count();
    res.block = opt.params.block();
    res.max_batch = opt.params.max_batch();

    // The session used for the score table and for the cost measurements.
    report("generating keys");
    Client client;
    if (!client.init(opt.params, opt.fold, error)) {
        std::cerr << "ffv_bench: " << error << "\n";
        return 6;
    }
    res.keys = client.key_sizes();
    res.keygen_ms = client.keygen_ms();
    res.chain = modulus_chain(client.context());

    Server server;
    if (!attach_server(opt.params, opt.fold, client.context_ptr(), client.relin_keys(),
                       client.galois_keys(), server, error)) {
        std::cerr << "ffv_bench: " << error << "\n";
        return 6;
    }

    report("scoring every pair under encryption");
    if (!compute_scores(opt, set, client, server, res.scores, error)) {
        std::cerr << "ffv_bench: " << error << "\n";
        return 7;
    }

    report("deriving verification metrics");
    res.eval_cleartext = evaluate(res.scores.cleartext, opt.target_fars);
    res.eval_encrypted = evaluate(res.scores.encrypted, opt.target_fars);
    res.equivalence =
        compare_decisions(res.scores.cleartext, res.scores.encrypted, res.eval_cleartext.protocol);

    report("measuring per-stage cost");
    if (!measure_cost(opt, set, res, error)) {
        std::cerr << "ffv_bench: " << error << "\n";
        return 8;
    }

    report("measuring slot-packed batching");
    if (!measure_batching(opt, set, res, error)) {
        std::cerr << "ffv_bench: " << error << "\n";
        return 9;
    }

    if (!opt.skip_scale) {
        report("sweeping the scaling factor");
        if (!measure_scale(opt, set, res, error)) {
            std::cerr << "ffv_bench: " << error << "\n";
            return 10;
        }
        res.scale_fit = fit_scale(res.scale);
    }

    // The pair vectors are large and already summarised, so only the metadata
    // travels into the results record.
    res.meta = set;
    res.meta.pairs.clear();
    res.meta.dim = set.dim;
    res.total_wall_seconds = wall.ms() / 1000.0;

    if (!make_dirs(opt.out_dir, error) || !write_json(res, opt.out_json, error)
        || !write_scores_csv(res.scores, opt.out_scores, error)) {
        std::cerr << "ffv_bench: " << error << "\n";
        return 11;
    }

    std::cout << "\n"
              << "accuracy (cleartext) : " << res.eval_cleartext.protocol.accuracy_mean * 100.0
              << "% +/- " << res.eval_cleartext.protocol.accuracy_stddev * 100.0 << "\n"
              << "accuracy (encrypted) : " << res.eval_encrypted.protocol.accuracy_mean * 100.0
              << "% +/- " << res.eval_encrypted.protocol.accuracy_stddev * 100.0 << "\n"
              << "max score error      : " << res.equivalence.max_abs_error << " ("
              << res.equivalence.precision_bits << " bits)\n"
              << "error / margin        : " << res.equivalence.ratio
              << (res.equivalence.proved_zero_flips ? "  [below 1: no decision can change]"
                                                    : "  [at or above 1: a decision could change]")
              << "\n"
              << "decision flips        : " << res.equivalence.observed_flips << "\n"
              << "wrote " << opt.out_json << " and " << opt.out_scores << " in "
              << res.total_wall_seconds << " s\n";
    return 0;
}

} // namespace bench
} // namespace ffv
