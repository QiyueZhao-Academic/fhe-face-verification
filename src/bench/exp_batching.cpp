// SPDX-License-Identifier: MIT
//
// Slot-packed batching.
//
// A ciphertext at degree N carries N/2 slots, and one template of dimension d
// occupies the next power of two above d. So N/(2 * block) templates fit side by
// side, and one pass of the circuit scores all of them: the multiply is
// element-wise, and the rotate-and-sum fold leaves each block's inner product in
// that block's first slot because the block length divides the slot count.
//
// The circuit is the same at every batch size, so the cost of a batch is close to
// the cost of a single verification and both latency and bandwidth per
// verification fall by the batch size.

#include "bench.hpp"

#include <algorithm>
#include <cmath>

namespace ffv {
namespace bench {

bool measure_batching(const Options& opt, const TemplateSet& set, Results& res, std::string& error)
{
    Client client;
    if (!client.init(opt.params, opt.fold, error)) return false;
    Server server;
    if (!attach_server(opt.params, opt.fold, client.context_ptr(), client.relin_keys(),
                       client.galois_keys(), server, error)) {
        return false;
    }

    const std::size_t max_batch = opt.params.max_batch();
    const std::size_t n = set.pairs.size();
    // A batch of B needs B distinct pairs, and the timing needs a few repetitions.
    const int reps = std::max(3, opt.cost_reps / 2);

    for (int b_req : opt.batch_sweep) {
        if (b_req < 1) continue;
        const std::size_t b = std::min(static_cast<std::size_t>(b_req), max_batch);
        BatchPoint pt;
        pt.batch = static_cast<int>(b);

        std::vector<double> srv_ms;
        double worst = 0.0;
        for (int r = 0; r < reps; ++r) {
            std::vector<std::vector<double>> probes, enrolled;
            std::vector<double> reference;
            probes.reserve(b);
            enrolled.reserve(b);
            for (std::size_t k = 0; k < b; ++k) {
                const Pair& p = set.pairs[(static_cast<std::size_t>(r) * b + k) % n];
                probes.push_back(p.a);
                enrolled.push_back(p.b);
                reference.push_back(cosine(p.a, p.b));
            }
            try {
                const seal::Ciphertext ca = client.encrypt_batch(probes);
                const seal::Ciphertext cb = client.encrypt_batch(enrolled);
                Trace tr;
                const Timer t;
                const seal::Ciphertext cr = score_ct_ct(server, ca, cb, &tr);
                srv_ms.push_back(t.ms());
                const std::vector<double> got = client.read_scores(cr, b);
                for (std::size_t k = 0; k < b; ++k) {
                    worst = std::max(worst, std::fabs(got[k] - reference[k]));
                }
                if (r == 0) pt.ciphertext = byte_size(ca);
            } catch (const std::exception& e) {
                error = std::string("batching measurement failed at batch ")
                        + std::to_string(b) + ": " + e.what();
                return false;
            }
        }
        pt.server_ms = summarise(srv_ms);
        pt.amortised_ms = pt.server_ms.median / static_cast<double>(b);
        pt.bytes_per_verification =
            static_cast<double>(pt.ciphertext.wire) / static_cast<double>(b);
        pt.throughput_per_second = pt.amortised_ms > 0.0 ? 1000.0 / pt.amortised_ms : 0.0;
        pt.max_abs_error = worst;
        res.batching.push_back(pt);

        if (b == max_batch) break; // larger requests would repeat this point
    }
    return true;
}

} // namespace bench
} // namespace ffv
