// SPDX-License-Identifier: MIT
//
// Cost of one unbatched 1:1 verification, broken down by stage.
//
// Three configurations are timed. The ct x ct circuit encrypts both templates,
// so the server learns neither. The ct x pt circuit keeps the enrolled template
// in the clear, which removes one key-switch from the critical path and shows
// what that privacy property costs. The naive fold performs d-1 rotations in
// place of log2(d) and serves as the cost baseline the report compares against.

#include "bench.hpp"

#include <algorithm>
#include <cmath>

namespace ffv {
namespace bench {

namespace {

// Runs `reps` unbatched verifications and fills a CostResult.
bool time_one(const Params& p, Fold f, Mode m, const TemplateSet& set, int reps, CostResult& out,
              std::string& error)
{
    Client client;
    if (!client.init(p, f, error)) return false;
    Server server;
    if (!attach_server(p, f, client.context_ptr(), client.relin_keys(), client.galois_keys(),
                       server, error)) {
        return false;
    }

    out.mode = m;
    out.fold = f;
    std::vector<double> enc_ms, srv_ms, dec_ms, mul_ms, rel_ms, res_ms, fold_ms;
    double worst = 0.0;
    const std::size_t n = set.pairs.size();

    for (int r = 0; r < reps; ++r) {
        const Pair& pair = set.pairs[static_cast<std::size_t>(r) % n];
        try {
            Timer t;
            const seal::Ciphertext ca = client.encrypt(pair.a);
            seal::Ciphertext cb;
            seal::Plaintext pb;
            if (m == Mode::CtCt) cb = client.encrypt(pair.b);
            else pb = client.encode_at(pair.b, ca);
            enc_ms.push_back(t.ms());

            Trace tr;
            t.reset();
            const seal::Ciphertext cr =
                m == Mode::CtCt ? score_ct_ct(server, ca, cb, &tr) : score_ct_pt(server, ca, pb, &tr);
            srv_ms.push_back(t.ms());
            mul_ms.push_back(tr.ms_multiply);
            rel_ms.push_back(tr.ms_relinearize);
            res_ms.push_back(tr.ms_rescale);
            fold_ms.push_back(tr.ms_fold);
            out.rotations = tr.rotations;

            t.reset();
            const double score = client.read_score(cr, 0);
            dec_ms.push_back(t.ms());

            worst = std::max(worst, std::fabs(score - cosine(pair.a, pair.b)));
            if (r == 0) {
                out.fresh_ciphertext = byte_size(ca);
                out.result_ciphertext = byte_size(cr);
            }
        } catch (const std::exception& e) {
            error = std::string("cost measurement failed: ") + e.what();
            return false;
        }
    }

    out.encrypt_ms = summarise(enc_ms);
    out.server_ms = summarise(srv_ms);
    out.decrypt_ms = summarise(dec_ms);
    out.multiply_ms = summarise(mul_ms);
    out.relinearize_ms = summarise(rel_ms);
    out.rescale_ms = summarise(res_ms);
    out.fold_ms = summarise(fold_ms);
    out.max_abs_error = worst;

    // The probe ciphertext is sent on every verification. In ct x ct mode the
    // enrolled ciphertext is stored once at enrolment and is not re-sent, so the
    // per-verification uplink is one ciphertext either way.
    out.uplink_bytes_per_verification = static_cast<double>(out.fresh_ciphertext.wire);
    out.downlink_bytes_per_verification = static_cast<double>(out.result_ciphertext.wire);
    return true;
}

} // namespace

bool measure_cost(const Options& opt, const TemplateSet& set, Results& res, std::string& error)
{
    if (!time_one(opt.params, opt.fold, Mode::CtCt, set, opt.cost_reps, res.cost_ct_ct, error)) {
        return false;
    }
    if (!time_one(opt.params, opt.fold, Mode::CtPt, set, opt.cost_reps, res.cost_ct_pt, error)) {
        return false;
    }
    if (!opt.skip_naive) {
        // The naive fold costs d-1 key-switches, so a handful of repetitions is
        // enough to establish the ratio.
        if (!time_one(opt.params, Fold::Naive, Mode::CtCt, set, std::max(1, opt.naive_reps),
                      res.cost_naive, error)) {
            return false;
        }
        res.have_naive = true;
    }
    return true;
}

} // namespace bench
} // namespace ffv
