// SPDX-License-Identifier: MIT
//
// Scores every pair twice: once in the clear as the reference, and once through
// the homomorphic circuit. Everything the report says about fidelity, decision
// equivalence and verification accuracy is derived from this one table, so the
// two score vectors are produced in the same pass over the same pair order.
//
// Templates are packed side by side inside a single ciphertext. Slot packing
// changes neither the circuit nor the noise seen by any individual score, and it
// divides the wall time of a full LFW sweep by the batch size. The unbatched
// latency of one verification is measured separately in exp_cost.cpp.

#include "bench.hpp"

#include <algorithm>
#include <cstdio>
#include <iostream>

namespace ffv {
namespace bench {

bool compute_scores(const Options& opt, const TemplateSet& set, Client& client, Server& server,
                    ScoreTable& out, std::string& error)
{
    const std::size_t max_batch = opt.params.max_batch();
    if (max_batch == 0) {
        error = "one template does not fit in the available slots";
        return false;
    }
    std::size_t batch = opt.score_batch > 0 ? static_cast<std::size_t>(opt.score_batch) : max_batch;
    batch = std::min(batch, max_batch);
    batch = std::max<std::size_t>(batch, 1);
    out.batch = static_cast<int>(batch);

    const std::size_t n = set.pairs.size();
    out.cleartext.reserve(n);
    out.encrypted.reserve(n);

    const Timer wall;
    bool have_trace = false;
    std::size_t done = 0;

    for (std::size_t start = 0; start < n; start += batch) {
        const std::size_t take = std::min(batch, n - start);
        std::vector<std::vector<double>> probes, enrolled;
        probes.reserve(take);
        enrolled.reserve(take);
        for (std::size_t k = 0; k < take; ++k) {
            probes.push_back(set.pairs[start + k].a);
            enrolled.push_back(set.pairs[start + k].b);
        }

        try {
            Timer t;
            const seal::Ciphertext ca = client.encrypt_batch(probes);
            seal::Ciphertext cb;
            seal::Plaintext pb;
            if (opt.mode == Mode::CtCt) {
                cb = client.encrypt_batch(enrolled);
            } else {
                pb = client.encode_batch_at(enrolled, ca);
            }
            out.ms_encrypt_total += t.ms();

            Trace tr;
            t.reset();
            const seal::Ciphertext cr = opt.mode == Mode::CtCt
                                            ? score_ct_ct(server, ca, cb, &tr)
                                            : score_ct_pt(server, ca, pb, &tr);
            out.ms_server_total += t.ms();
            ++out.calls;
            if (!have_trace) {
                out.trace = tr;
                have_trace = true;
            }

            t.reset();
            const std::vector<double> scores = client.read_scores(cr, take);
            out.ms_decrypt_total += t.ms();

            for (std::size_t k = 0; k < take; ++k) {
                const Pair& p = set.pairs[start + k];
                Sample sc;
                sc.genuine = p.genuine;
                sc.fold = p.fold;
                sc.score = cosine(p.a, p.b);
                out.cleartext.push_back(sc);
                Sample se = sc;
                se.score = scores[k];
                out.encrypted.push_back(se);
            }
        } catch (const std::exception& e) {
            error = std::string("homomorphic scoring failed at pair ") + std::to_string(start)
                    + ": " + e.what();
            return false;
        }

        done += take;
        if (done % 1000 == 0 || done == n) {
            std::cout << "    " << done << "/" << n << " pairs" << std::endl;
        }
    }
    out.ms_wall_total = wall.ms();
    return true;
}

bool write_scores_csv(const ScoreTable& t, const std::string& path, std::string& error)
{
    FILE* f = std::fopen(path.c_str(), "w");
    if (!f) {
        error = "cannot write " + path;
        return false;
    }
    std::fprintf(f, "index,fold,label,score_cleartext,score_encrypted,abs_error\n");
    const std::size_t n = std::min(t.cleartext.size(), t.encrypted.size());
    for (std::size_t i = 0; i < n; ++i) {
        const double a = t.cleartext[i].score, b = t.encrypted[i].score;
        std::fprintf(f, "%zu,%d,%d,%.17g,%.17g,%.17g\n", i, t.cleartext[i].fold,
                     t.cleartext[i].genuine ? 1 : 0, a, b, a > b ? a - b : b - a);
    }
    std::fclose(f);
    return true;
}

} // namespace bench
} // namespace ffv
