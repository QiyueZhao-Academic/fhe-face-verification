// SPDX-License-Identifier: MIT

#include "ffv/crypto.hpp"

#include <algorithm>
#include <sstream>

namespace ffv {

std::string fold_name(Fold f) { return f == Fold::Log2 ? "log2" : "naive"; }

bool parse_fold(const std::string& text, Fold& out)
{
    if (text == "log2") { out = Fold::Log2; return true; }
    if (text == "naive") { out = Fold::Naive; return true; }
    return false;
}

std::string mode_name(Mode m) { return m == Mode::CtCt ? "ct_ct" : "ct_pt"; }

bool parse_mode(const std::string& text, Mode& out)
{
    if (text == "ct_ct") { out = Mode::CtCt; return true; }
    if (text == "ct_pt") { out = Mode::CtPt; return true; }
    return false;
}

std::size_t Params::block() const
{
    std::size_t b = 1;
    while (b < dim) b <<= 1;
    return b;
}

int Params::log2_block() const
{
    int k = 0;
    for (std::size_t b = block(); b > 1; b >>= 1) ++k;
    return k;
}

std::vector<int> Params::rotation_steps(Fold f) const
{
    std::vector<int> steps;
    if (f == Fold::Log2) {
        for (std::size_t s = 1; s < block(); s <<= 1) steps.push_back(static_cast<int>(s));
    } else {
        steps.push_back(1);
    }
    return steps;
}

int Params::rotation_count(Fold f) const
{
    return f == Fold::Log2 ? log2_block() : static_cast<int>(block()) - 1;
}

ParamCheck check_params(const Params& p)
{
    ParamCheck c;
    std::ostringstream msg;

    const std::size_t n = p.poly_modulus_degree;
    if (n < 1024 || (n & (n - 1)) != 0) {
        c.message = "poly_modulus_degree must be a power of two and at least 1024; got "
                    + std::to_string(n);
        return c;
    }
    if (p.dim == 0) {
        c.message = "template dimension must be positive";
        return c;
    }
    if (p.block() > p.slot_count()) {
        msg << "one template needs " << p.block() << " slots but poly_modulus_degree " << n
            << " provides only " << p.slot_count() << "; raise poly_modulus_degree";
        c.message = msg.str();
        return c;
    }

    const std::vector<int> bits = p.coeff_bit_sizes();
    for (int b : bits) {
        if (b < 20 || b > 60) {
            c.message = "every coefficient prime must be 20..60 bits; got " + std::to_string(b);
            return c;
        }
    }
    c.total_coeff_bits = 0;
    for (int b : bits) c.total_coeff_bits += b;
    c.max_coeff_bits = seal::CoeffModulus::MaxBitCount(n, p.sec_level);
    if (c.total_coeff_bits > c.max_coeff_bits) {
        msg << "coefficient modulus of " << c.total_coeff_bits << " bits exceeds the "
            << c.max_coeff_bits << " bits allowed at degree " << n << " and "
            << sec_level_name(p.sec_level)
            << "; lower scale_bits or raise poly_modulus_degree";
        c.message = msg.str();
        return c;
    }

    // A single ct x ct product doubles the scale; the rescale then divides it by
    // the middle prime. Decoding stays correct while the surviving prime is
    // wider than the scale it carries.
    if (p.scale_bits >= p.last_prime_bits) {
        msg << "scale_bits (" << p.scale_bits << ") must stay below last_prime_bits ("
            << p.last_prime_bits << ") to leave headroom for the integer part";
        c.message = msg.str();
        return c;
    }

    c.ok = true;
    c.message = "ok";
    return c;
}

std::shared_ptr<seal::SEALContext> make_context(const Params& p, std::string& error)
{
    const ParamCheck c = check_params(p);
    if (!c.ok) {
        error = c.message;
        return {};
    }
    try {
        seal::EncryptionParameters parms(seal::scheme_type::ckks);
        parms.set_poly_modulus_degree(p.poly_modulus_degree);
        parms.set_coeff_modulus(
            seal::CoeffModulus::Create(p.poly_modulus_degree, p.coeff_bit_sizes()));
        auto ctx = std::make_shared<seal::SEALContext>(parms, true, p.sec_level);
        if (!ctx->parameters_set()) {
            error = std::string("SEAL rejected the parameters: ")
                    + ctx->parameter_error_message();
            return {};
        }
        error.clear();
        return ctx;
    } catch (const std::exception& e) {
        error = std::string("SEAL threw while building the context: ") + e.what();
        return {};
    }
}

std::vector<LevelInfo> modulus_chain(const seal::SEALContext& ctx)
{
    std::vector<LevelInfo> out;
    auto data = ctx.key_context_data();
    while (data) {
        LevelInfo info;
        info.chain_index = static_cast<int>(data->chain_index());
        info.is_key_level = (data->parms_id() == ctx.key_parms_id());
        info.total_bits = 0;
        for (const auto& m : data->parms().coeff_modulus()) {
            const int b = static_cast<int>(m.bit_count());
            info.prime_bits.push_back(b);
            info.total_bits += b;
        }
        out.push_back(info);
        data = data->next_context_data();
    }
    return out;
}

int chain_index_of(const seal::SEALContext& ctx, const seal::Ciphertext& ct)
{
    auto data = ctx.get_context_data(ct.parms_id());
    return data ? static_cast<int>(data->chain_index()) : -1;
}

std::string sec_level_name(seal::sec_level_type level)
{
    switch (level) {
    case seal::sec_level_type::none: return "none";
    case seal::sec_level_type::tc128: return "tc128";
    case seal::sec_level_type::tc192: return "tc192";
    case seal::sec_level_type::tc256: return "tc256";
    }
    return "unknown";
}

std::string seal_version()
{
    std::ostringstream s;
    s << SEAL_VERSION_MAJOR << '.' << SEAL_VERSION_MINOR << '.' << SEAL_VERSION_PATCH;
    return s.str();
}

std::string compression_name()
{
    switch (seal::Serialization::compr_mode_default) {
    case seal::compr_mode_type::none: return "none";
#ifdef SEAL_USE_ZLIB
    case seal::compr_mode_type::zlib: return "zlib";
#endif
#ifdef SEAL_USE_ZSTD
    case seal::compr_mode_type::zstd: return "zstd";
#endif
    default: break;
    }
    return "other";
}

std::vector<double> pack(const std::vector<double>& v, std::size_t slots, std::size_t slot)
{
    std::vector<double> buf(slots, 0.0);
    const std::size_t n = std::min(v.size(), slots - std::min(slot, slots));
    for (std::size_t i = 0; i < n; ++i) buf[slot + i] = v[i];
    return buf;
}

} // namespace ffv
