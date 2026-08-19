// SPDX-License-Identifier: MIT
//
// Precision against the CKKS scaling factor.
//
// A CKKS plaintext holds round(Delta * m), and decoding returns m + e / Delta
// where e is the ciphertext noise. The noise depends on the modulus widths and on
// the number of key switches, and not on Delta, so doubling Delta halves the
// absolute error. The predicted slope of precision against scale bits is
// therefore exactly 1, with no constant available to tune against the data.
//
// The sweep measures that slope. The intercept is the circuit's noise floor,
// -log2|e|, and is reported as a measurement of this circuit on this host.

#include "bench.hpp"

#include <algorithm>
#include <cmath>

namespace ffv {
namespace bench {

bool measure_scale(const Options& opt, const TemplateSet& set, Results& res, std::string& error)
{
    const std::size_t n = set.pairs.size();
    const int reps = std::max(1, std::min(opt.scale_pairs, static_cast<int>(n)));

    for (int bits : opt.scale_bits_sweep) {
        ScalePoint pt;
        Params p = opt.params;
        p.scale_bits = bits;
        pt.scale_bits = bits;
        pt.last_prime_bits = p.last_prime_bits;
        pt.headroom_bits = p.last_prime_bits - bits;

        const ParamCheck chk = check_params(p);
        pt.total_coeff_bits = chk.total_coeff_bits;
        if (!chk.ok) {
            pt.usable = false;
            pt.note = chk.message;
            res.scale.push_back(pt);
            continue;
        }

        Client client;
        std::string local;
        if (!client.init(p, opt.fold, local)) {
            pt.usable = false;
            pt.note = local;
            res.scale.push_back(pt);
            continue;
        }
        Server server;
        if (!attach_server(p, opt.fold, client.context_ptr(), client.relin_keys(),
                           client.galois_keys(), server, local)) {
            error = local;
            return false;
        }

        double worst = 0.0;
        std::vector<double> srv_ms;
        bool ok = true;
        for (int r = 0; r < reps; ++r) {
            const Pair& pair = set.pairs[static_cast<std::size_t>(r) % n];
            try {
                const seal::Ciphertext ca = client.encrypt(pair.a);
                const seal::Ciphertext cb = client.encrypt(pair.b);
                Trace tr;
                const Timer t;
                const seal::Ciphertext cr = score_ct_ct(server, ca, cb, &tr);
                srv_ms.push_back(t.ms());
                const double got = client.read_score(cr, 0);
                worst = std::max(worst, std::fabs(got - cosine(pair.a, pair.b)));
            } catch (const std::exception& e) {
                // A scale this wide leaves too little headroom for the circuit;
                // the point is recorded as unusable with the reason SEAL gave.
                pt.usable = false;
                pt.note = e.what();
                ok = false;
                break;
            }
        }
        if (!ok) {
            res.scale.push_back(pt);
            continue;
        }

        pt.usable = true;
        pt.note = "ok";
        pt.max_abs_error = worst;
        pt.precision_bits = worst > 0.0 ? -std::log2(worst) : 0.0;
        pt.server_ms = summarise(srv_ms).median;
        res.scale.push_back(pt);
    }
    return true;
}

ScaleFit fit_scale(const std::vector<ScalePoint>& points)
{
    ScaleFit fit;
    // Every usable point enters the fit. No point is excluded, so the slope is
    // not the product of a selection made after looking at the residuals.
    std::vector<double> xs, ys;
    for (const ScalePoint& p : points) {
        if (p.usable && p.precision_bits > 0.0) {
            xs.push_back(static_cast<double>(p.scale_bits));
            ys.push_back(p.precision_bits);
        }
    }
    fit.points_used = static_cast<int>(xs.size());
    if (fit.points_used < 2) return fit;

    double sx = 0.0, sy = 0.0;
    for (std::size_t i = 0; i < xs.size(); ++i) { sx += xs[i]; sy += ys[i]; }
    const double mx = sx / xs.size(), my = sy / ys.size();
    double sxy = 0.0, sxx = 0.0;
    for (std::size_t i = 0; i < xs.size(); ++i) {
        sxy += (xs[i] - mx) * (ys[i] - my);
        sxx += (xs[i] - mx) * (xs[i] - mx);
    }
    fit.measured_slope = sxx > 0.0 ? sxy / sxx : 0.0;
    fit.intercept_bits = my - fit.measured_slope * mx;
    fit.slope_deviation = fit.measured_slope - fit.predicted_slope;

    double ss_res = 0.0, ss_tot = 0.0;
    for (std::size_t i = 0; i < xs.size(); ++i) {
        const double pred = fit.measured_slope * xs[i] + fit.intercept_bits;
        const double r = ys[i] - pred;
        fit.max_residual_bits = std::max(fit.max_residual_bits, std::fabs(r));
        ss_res += r * r;
        ss_tot += (ys[i] - my) * (ys[i] - my);
    }
    fit.r_squared = ss_tot > 0.0 ? 1.0 - ss_res / ss_tot : 0.0;
    return fit;
}

} // namespace bench
} // namespace ffv
