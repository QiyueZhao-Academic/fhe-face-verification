// SPDX-License-Identifier: MIT
//
// See include/ffv/server.hpp: this translation unit must stay free of any
// reference to the secret key or to decryption.

#include "ffv/server.hpp"

#include <fstream>

#include "ffv/io.hpp"
#include "ffv/timing.hpp"

namespace ffv {

namespace {

template <typename T>
bool load_key(T& object, const seal::SEALContext& ctx, const std::string& path,
              std::string& error)
{
    std::ifstream in(path.c_str(), std::ios::binary);
    if (!in) {
        error = "missing evaluation key " + path;
        return false;
    }
    try {
        object.load(ctx, in);
    } catch (const std::exception& e) {
        error = "cannot parse " + path + ": " + e.what();
        return false;
    }
    return true;
}

// Rotate-and-sum. With doubling strides, slot i ends up holding the sum of the
// `block` consecutive slots starting at i. Because the block length divides the
// slot count and every template is block-aligned, the first slot of each block
// holds exactly that block's inner product.
void fold_inplace(Server& s, seal::Ciphertext& ct, Fold f, int& rotations)
{
    const std::size_t blk = s.params.block();
    seal::Ciphertext rot;
    if (f == Fold::Log2) {
        for (std::size_t step = 1; step < blk; step <<= 1) {
            s.eval->rotate_vector(ct, static_cast<int>(step), s.galois_keys, rot);
            s.eval->add_inplace(ct, rot);
            ++rotations;
        }
    } else {
        seal::Ciphertext acc = ct;
        seal::Ciphertext cur = ct;
        for (std::size_t k = 1; k < blk; ++k) {
            s.eval->rotate_vector(cur, 1, s.galois_keys, rot);
            cur = rot;
            s.eval->add_inplace(acc, cur);
            ++rotations;
        }
        ct = acc;
    }
}

void finish(Server& s, seal::Ciphertext& ct, Fold f, Trace* tr, const Timer& total)
{
    int rotations = 0;
    const Timer t;
    fold_inplace(s, ct, f, rotations);
    if (tr) {
        tr->ms_fold = t.ms();
        tr->rotations = rotations;
        tr->level_out = chain_index_of(*s.ctx, ct);
        tr->scale_out = ct.scale();
        tr->ms_total = total.ms();
    }
}

} // namespace

bool open_server(const std::string& pub_dir, Server& out, std::string& error)
{
    if (!read_session(join(pub_dir, "session.txt"), out.params, out.fold, error)) return false;
    out.ctx = make_context(out.params, error);
    if (!out.ctx) return false;
    if (!load_key(out.relin_keys, *out.ctx, join(pub_dir, "relin.key"), error)) return false;
    if (!load_key(out.galois_keys, *out.ctx, join(pub_dir, "galois.key"), error)) return false;
    out.eval = std::make_unique<seal::Evaluator>(*out.ctx);
    return true;
}

bool attach_server(const Params& p, Fold f, std::shared_ptr<seal::SEALContext> ctx,
                   const seal::RelinKeys& rk, const seal::GaloisKeys& gk, Server& out,
                   std::string& error)
{
    if (!ctx) {
        error = "attach_server received an empty context";
        return false;
    }
    out.params = p;
    out.fold = f;
    out.ctx = std::move(ctx);
    out.relin_keys = rk;
    out.galois_keys = gk;
    out.eval = std::make_unique<seal::Evaluator>(*out.ctx);
    return true;
}

seal::Ciphertext score_ct_ct(Server& s, const seal::Ciphertext& a, const seal::Ciphertext& b,
                             Trace* trace)
{
    const Timer total;
    seal::Ciphertext ct;
    if (trace) {
        trace->level_in = chain_index_of(*s.ctx, a);
        trace->scale_in = a.scale();
    }

    Timer t;
    s.eval->multiply(a, b, ct);
    if (trace) {
        trace->ms_multiply = t.ms();
        trace->level_after_mul = chain_index_of(*s.ctx, ct);
        trace->scale_after_mul = ct.scale();
    }

    t.reset();
    s.eval->relinearize_inplace(ct, s.relin_keys);
    if (trace) trace->ms_relinearize = t.ms();

    t.reset();
    s.eval->rescale_to_next_inplace(ct);
    if (trace) trace->ms_rescale = t.ms();

    finish(s, ct, s.fold, trace, total);
    return ct;
}

seal::Ciphertext score_ct_pt(Server& s, const seal::Ciphertext& a, const seal::Plaintext& b,
                             Trace* trace)
{
    const Timer total;
    seal::Ciphertext ct;
    if (trace) {
        trace->level_in = chain_index_of(*s.ctx, a);
        trace->scale_in = a.scale();
    }

    Timer t;
    s.eval->multiply_plain(a, b, ct);
    if (trace) {
        trace->ms_multiply = t.ms();
        trace->ms_relinearize = 0.0; // a plaintext factor leaves the ciphertext size unchanged
        trace->level_after_mul = chain_index_of(*s.ctx, ct);
        trace->scale_after_mul = ct.scale();
    }

    t.reset();
    s.eval->rescale_to_next_inplace(ct);
    if (trace) trace->ms_rescale = t.ms();

    finish(s, ct, s.fold, trace, total);
    return ct;
}

} // namespace ffv
