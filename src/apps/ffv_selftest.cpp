// SPDX-License-Identifier: MIT
//
// Self-test. Six suites, each of which fails loudly with the observed value.
// Every claim the report makes about correctness has a check here.

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <random>
#include <string>
#include <vector>

#include "ffv/client.hpp"
#include "ffv/io.hpp"
#include "ffv/metrics.hpp"
#include "ffv/platform.hpp"
#include "ffv/server.hpp"
#include "ffv/templates.hpp"

using namespace ffv;

namespace {

int g_failures = 0;
int g_checks = 0;
std::string g_suite;

void suite(const std::string& name)
{
    g_suite = name;
    std::cout << "\n[" << name << "]\n";
}

void ok(bool condition, const std::string& what, const std::string& detail = "")
{
    ++g_checks;
    if (condition) {
        std::cout << "  pass  " << what << (detail.empty() ? "" : "  (" + detail + ")") << "\n";
    } else {
        ++g_failures;
        std::cout << "  FAIL  " << what << (detail.empty() ? "" : "  (" + detail + ")") << "\n";
    }
}

std::string num(double v)
{
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.6g", v);
    return buf;
}

// Deterministic unit vectors, so a failure is reproducible from the seed alone.
std::vector<double> unit_vector(std::mt19937_64& rng, std::size_t dim)
{
    std::normal_distribution<double> gauss(0.0, 1.0);
    std::vector<double> v(dim);
    double norm = 0.0;
    for (std::size_t i = 0; i < dim; ++i) { v[i] = gauss(rng); norm += v[i] * v[i]; }
    norm = std::sqrt(norm);
    for (std::size_t i = 0; i < dim; ++i) v[i] /= norm;
    return v;
}

// ---------------------------------------------------------------------------

void test_parameters()
{
    suite("parameters");
    Params p;
    ParamCheck c = check_params(p);
    ok(c.ok, "the default configuration is accepted", c.message);
    ok(c.total_coeff_bits <= c.max_coeff_bits,
       "the coefficient modulus stays inside the security bound",
       std::to_string(c.total_coeff_bits) + " of " + std::to_string(c.max_coeff_bits) + " bits");
    ok(p.block() == 512 && p.log2_block() == 9, "a 512-dimensional template occupies 512 slots",
       std::to_string(p.block()) + " slots, " + std::to_string(p.log2_block()) + " strides");
    ok(p.max_batch() == 8, "eight templates fit in one ciphertext at degree 8192",
       std::to_string(p.max_batch()));
    ok(p.rotation_count(Fold::Log2) == 9 && p.rotation_count(Fold::Naive) == 511,
       "the two folds cost 9 and 511 rotations");

    Params bad = p;
    bad.scale_bits = 60;
    ok(!check_params(bad).ok, "a scale as wide as the surviving prime is rejected",
       check_params(bad).message);
    bad = p;
    bad.poly_modulus_degree = 2048;
    ok(!check_params(bad).ok, "a degree too small for the modulus is rejected");
    bad = p;
    bad.dim = 100000;
    ok(!check_params(bad).ok, "a template larger than the slot count is rejected");

    // Padding to a power of two is what makes the fold exact.
    Params odd = p;
    odd.dim = 300;
    ok(odd.block() == 512, "a dimension of 300 pads to 512 slots", std::to_string(odd.block()));
}

void test_context()
{
    suite("context");
    Params p;
    std::string error;
    auto ctx = make_context(p, error);
    ok(static_cast<bool>(ctx), "the context builds", error);
    if (!ctx) return;
    const std::vector<LevelInfo> chain = modulus_chain(*ctx);
    ok(chain.size() == 3, "the modulus chain has a key level and two data levels",
       std::to_string(chain.size()) + " levels");
    ok(chain.back().total_bits == p.last_prime_bits,
       "the last level keeps exactly the surviving prime",
       std::to_string(chain.back().total_bits) + " bits");
    ok(sec_level_name(p.sec_level) == "tc128", "the security level is tc128");
}

void test_inner_product()
{
    suite("homomorphic inner product");
    Params p;
    std::string error;
    Client client;
    if (!client.init(p, Fold::Log2, error)) { ok(false, "key generation", error); return; }
    Server server;
    if (!attach_server(p, Fold::Log2, client.context_ptr(), client.relin_keys(),
                       client.galois_keys(), server, error)) {
        ok(false, "server attach", error);
        return;
    }

    std::mt19937_64 rng(20260817);
    double worst_ctct = 0.0, worst_ctpt = 0.0;
    int depth_ok = 0;
    for (int i = 0; i < 8; ++i) {
        const std::vector<double> a = unit_vector(rng, p.dim);
        const std::vector<double> b = unit_vector(rng, p.dim);
        const double reference = cosine(a, b);

        const seal::Ciphertext ca = client.encrypt(a);
        const seal::Ciphertext cb = client.encrypt(b);
        Trace tr;
        const seal::Ciphertext r1 = score_ct_ct(server, ca, cb, &tr);
        worst_ctct = std::max(worst_ctct, std::fabs(client.read_score(r1, 0) - reference));
        if (tr.rotations == 9 && tr.level_in == 1 && tr.level_out == 0) ++depth_ok;

        const seal::Plaintext pb = client.encode_at(b, ca);
        const seal::Ciphertext r2 = score_ct_pt(server, ca, pb, nullptr);
        worst_ctpt = std::max(worst_ctpt, std::fabs(client.read_score(r2, 0) - reference));
    }
    ok(worst_ctct < 1e-4, "the ct x ct circuit reproduces the cosine similarity",
       "max |error| " + num(worst_ctct));
    ok(worst_ctpt < 1e-4, "the ct x pt circuit reproduces the cosine similarity",
       "max |error| " + num(worst_ctpt));
    ok(depth_ok == 8, "one multiply and one rescale take the ciphertext from level 1 to level 0",
       std::to_string(depth_ok) + " of 8 calls");

    // A known value: the cosine of a vector with itself is exactly one.
    const std::vector<double> u = unit_vector(rng, p.dim);
    const seal::Ciphertext cu = client.encrypt(u);
    const seal::Ciphertext self = score_ct_ct(server, cu, cu, nullptr);
    const double got = client.read_score(self, 0);
    ok(std::fabs(got - 1.0) < 1e-4, "a template scored against itself returns one", num(got));

    // Orthogonal vectors: the fold must not leak a neighbouring slot.
    std::vector<double> e0(p.dim, 0.0), e1(p.dim, 0.0);
    e0[0] = 1.0;
    e1[1] = 1.0;
    const seal::Ciphertext r =
        score_ct_ct(server, client.encrypt(e0), client.encrypt(e1), nullptr);
    ok(std::fabs(client.read_score(r, 0)) < 1e-4, "orthogonal templates return zero",
       num(client.read_score(r, 0)));
}

void test_fold_and_batch()
{
    suite("fold equivalence and slot packing");
    Params p;
    std::string error;
    std::mt19937_64 rng(7);

    // The naive fold and the log2 fold must agree: they compute the same sum.
    std::vector<std::vector<double>> as, bs;
    std::vector<double> reference;
    for (std::size_t k = 0; k < p.max_batch(); ++k) {
        as.push_back(unit_vector(rng, p.dim));
        bs.push_back(unit_vector(rng, p.dim));
        reference.push_back(cosine(as.back(), bs.back()));
    }

    double worst_naive = 0.0, worst_log2 = 0.0, worst_batch = 0.0;
    for (int which = 0; which < 2; ++which) {
        const Fold f = which == 0 ? Fold::Log2 : Fold::Naive;
        Client client;
        if (!client.init(p, f, error)) { ok(false, "key generation", error); return; }
        Server server;
        if (!attach_server(p, f, client.context_ptr(), client.relin_keys(), client.galois_keys(),
                           server, error)) {
            ok(false, "server attach", error);
            return;
        }
        double worst = 0.0;
        for (std::size_t k = 0; k < 4; ++k) {
            const seal::Ciphertext ca = client.encrypt(as[k]);
            const seal::Ciphertext cb = client.encrypt(bs[k]);
            const double got = client.read_score(score_ct_ct(server, ca, cb, nullptr), 0);
            worst = std::max(worst, std::fabs(got - reference[k]));
        }
        if (f == Fold::Naive) worst_naive = worst; else worst_log2 = worst;

        if (f == Fold::Log2) {
            // All batch members are scored by one pass of the same circuit.
            const seal::Ciphertext ba = client.encrypt_batch(as);
            const seal::Ciphertext bb = client.encrypt_batch(bs);
            const seal::Ciphertext br = score_ct_ct(server, ba, bb, nullptr);
            const std::vector<double> got_all = client.read_scores(br, as.size());
            for (std::size_t k = 0; k < as.size(); ++k) {
                worst_batch = std::max(worst_batch, std::fabs(got_all[k] - reference[k]));
            }
        }
    }

    // Key-switch accounting. The log2 fold doubles the accumulated noise at each
    // of its log2(d) steps and adds one key switch, ending at d-1 units. The
    // naive fold rotates a chain of ciphertexts, so the k-th term carries k units
    // and the sum carries d(d-1)/2. The ratio of the two is exactly d/2, and that
    // factor is what the naive fold's error bound is scaled by.
    const double ks_ratio = static_cast<double>(p.dim) / 2.0;
    const double naive_bound = 1e-4 * ks_ratio;
    ok(worst_log2 < 1e-4, "the log2 fold agrees with the reference",
       "max |error| " + num(worst_log2));
    ok(worst_naive < naive_bound, "the d-1 rotation fold agrees with the reference",
       "max |error| " + num(worst_naive) + " against a bound of " + num(naive_bound));
    ok(worst_naive > worst_log2,
       "the d-1 fold is the less precise of the two, as its key-switch count predicts",
       num(worst_naive) + " against " + num(worst_log2));
    ok(worst_batch < 1e-4, "a packed batch of 8 returns 8 correct scores from one call",
       "max |error| " + num(worst_batch));
}

void test_metrics()
{
    suite("metrics");
    // A separable two-fold set with a known answer.
    std::vector<Sample> s;
    for (int f = 0; f < 2; ++f) {
        for (int i = 0; i < 50; ++i) {
            Sample g;
            g.genuine = true;
            g.fold = f;
            g.score = 0.7 + 0.001 * i;
            s.push_back(g);
            Sample im;
            im.genuine = false;
            im.fold = f;
            im.score = 0.1 + 0.001 * i;
            s.push_back(im);
        }
    }
    Evaluation e = evaluate(s, {1e-1, 1e-2, 1e-4});
    ok(std::fabs(e.auc - 1.0) < 1e-12, "a separable set gives an area under the curve of one",
       num(e.auc));
    ok(e.auc_saturated, "saturation at one is flagged");
    ok(std::fabs(e.protocol.accuracy_mean - 1.0) < 1e-12, "cross-validated accuracy is one",
       num(e.protocol.accuracy_mean));
    ok(e.protocol.min_abs_margin > 0.0,
       "every held-out pair keeps a positive distance from its threshold",
       num(e.protocol.min_abs_margin));

    // 100 impostor pairs cannot express a false accept rate of 1e-4.
    ok(e.operating_points.size() == 3, "one entry per requested operating point");
    ok(e.operating_points[0].resolvable, "1e-1 is resolvable with 100 impostor pairs");
    ok(!e.operating_points[2].resolvable, "1e-4 is refused with 100 impostor pairs",
       e.operating_points[2].note);
    ok(std::fabs(e.far_resolution - 0.01) < 1e-12, "the resolution is reported as 1/100",
       num(e.far_resolution));

    // Ties must not break the rank statistic.
    std::vector<Sample> tied;
    for (int i = 0; i < 10; ++i) {
        Sample a; a.genuine = true; a.fold = 0; a.score = 0.5; tied.push_back(a);
        Sample b; b.genuine = false; b.fold = 0; b.score = 0.5; tied.push_back(b);
    }
    ok(std::fabs(evaluate(tied, {}).auc - 0.5) < 1e-12,
       "a fully tied set gives an area of one half", num(evaluate(tied, {}).auc));

    // Equivalence: an error smaller than every margin proves no decision changes.
    std::vector<Sample> enc = s;
    for (Sample& x : enc) x.score += 1e-9;
    Equivalence eq = compare_decisions(s, enc, e.protocol);
    ok(eq.observed_flips == 0 && eq.proved_zero_flips,
       "a perturbation below the smallest margin cannot change a decision",
       "ratio " + num(eq.ratio));

    // An error larger than the margin must not be certified.
    std::vector<Sample> bad = s;
    for (Sample& x : bad) x.score += 0.5;
    Equivalence eq2 = compare_decisions(s, bad, e.protocol);
    ok(!eq2.proved_zero_flips, "a perturbation above the smallest margin is not certified",
       "ratio " + num(eq2.ratio));
    ok(eq2.observed_flips > 0, "and the flips it causes are counted",
       std::to_string(eq2.observed_flips));
}

void test_serialisation(const std::string& tmp)
{
    suite("session serialisation");
    Params p;
    std::string error;
    Client a;
    if (!a.init(p, Fold::Log2, error)) { ok(false, "key generation", error); return; }
    const std::string pub = join(tmp, "public"), sec = join(tmp, "private");
    ok(a.save(pub, sec, error), "a session writes public keys and a secret key", error);
    ok(file_exists(join(pub, "session.txt")) && file_exists(join(pub, "galois.key")),
       "the public directory holds the descriptor and the evaluation keys");
    ok(!file_exists(join(pub, "secret.key")),
       "the secret key is absent from the directory the server reads");

    Client b;
    ok(b.load(pub, sec, error), "the session reloads from disk", error);

    Server s;
    ok(open_server(pub, s, error), "the server opens the public directory", error);

    std::mt19937_64 rng(11);
    const std::vector<double> u = unit_vector(rng, p.dim), v = unit_vector(rng, p.dim);
    const seal::Ciphertext cu = b.encrypt(u), cv = b.encrypt(v);
    const double got = b.read_score(score_ct_ct(s, cu, cv, nullptr), 0);
    ok(std::fabs(got - cosine(u, v)) < 1e-4,
       "a score computed by the reloaded server decrypts correctly",
       "|error| " + num(std::fabs(got - cosine(u, v))));
}

void test_platform()
{
    suite("platform");
    const Platform p = describe_platform();
    ok(!p.os.empty() && p.os != "unknown", "the operating system is identified", p.os);
    ok(p.arch == "arm64" || p.arch == "x86_64", "the architecture is identified", p.arch);
    ok(p.logical_cores > 0, "the core count is read", std::to_string(p.logical_cores));
    ok(p.little_endian, "the host is little-endian, which the container format assumes");
    ok(!timing_caveat(p).empty(), "a timing caveat is produced", timing_caveat(p));
    ok(!seal_version().empty(), "the SEAL version is recorded", seal_version());
}

} // namespace

int main(int argc, char** argv)
{
    std::string tmp = "artifacts/selftest";
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--tmp" && i + 1 < argc) tmp = argv[++i];
    }
    std::string error;
    if (!make_dirs(tmp, error)) {
        std::cerr << "ffv_selftest: " << error << "\n";
        return 1;
    }

    test_parameters();
    test_context();
    test_inner_product();
    test_fold_and_batch();
    test_metrics();
    test_serialisation(tmp);
    test_platform();

    std::cout << "\n" << (g_checks - g_failures) << "/" << g_checks << " checks passed\n";
    if (g_failures) std::cout << g_failures << " check(s) failed\n";
    return g_failures == 0 ? 0 : 1;
}
