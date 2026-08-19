// SPDX-License-Identifier: MIT
//
// RNS-CKKS parameterisation shared by the client and the server.
//
// This header is compiled into both halves of the system, so it names only
// public material. The identifiers seal::SecretKey and seal::Decryptor appear
// nowhere in it, which is what allows the server library to include it.

#ifndef FFV_CRYPTO_HPP
#define FFV_CRYPTO_HPP

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include <seal/seal.h>

namespace ffv {

// How the d element-wise products are summed into a single slot.
enum class Fold {
    Log2,  // doubling strides, log2(d) rotations
    Naive  // unit strides, d-1 rotations (kept as a cost baseline)
};

std::string fold_name(Fold f);
bool parse_fold(const std::string& text, Fold& out);

// Which operand the server holds in the clear.
enum class Mode {
    CtCt,  // both templates encrypted: the server learns neither
    CtPt   // enrolled template in the clear, probe encrypted
};

std::string mode_name(Mode m);
bool parse_mode(const std::string& text, Mode& out);

struct Params {
    std::size_t poly_modulus_degree = 8192;
    int scale_bits = 40;         // log2 of the CKKS scaling factor Delta
    int last_prime_bits = 60;    // the prime that survives the single rescale
    int special_prime_bits = 60; // key-switching prime
    std::size_t dim = 512;       // template dimension
    seal::sec_level_type sec_level = seal::sec_level_type::tc128;

    // SEAL consumes the primes in this order; the final entry is the
    // key-switching prime and carries no plaintext.
    std::vector<int> coeff_bit_sizes() const
    {
        return {last_prime_bits, scale_bits, special_prime_bits};
    }
    double scale() const { return std::pow(2.0, static_cast<double>(scale_bits)); }
    std::size_t slot_count() const { return poly_modulus_degree / 2; }

    // The fold is exact only when the block length is a power of two, so a
    // template of dimension d occupies the next power of two in slots.
    std::size_t block() const;
    int log2_block() const;

    // Templates that fit side by side in one ciphertext.
    std::size_t max_batch() const { return slot_count() / block(); }

    std::vector<int> rotation_steps(Fold f) const;
    int rotation_count(Fold f) const;
};

// Result of checking a configuration before SEAL is asked to do anything.
struct ParamCheck {
    bool ok = false;
    std::string message;
    int total_coeff_bits = 0;
    int max_coeff_bits = 0;
};

ParamCheck check_params(const Params& p);

// Returns an empty shared_ptr and fills `error` when the parameters are
// unusable, so no caller has to catch a SEAL exception.
std::shared_ptr<seal::SEALContext> make_context(const Params& p, std::string& error);

struct LevelInfo {
    int chain_index = 0;
    int total_bits = 0;
    std::vector<int> prime_bits;
    bool is_key_level = false;
};

std::vector<LevelInfo> modulus_chain(const seal::SEALContext& ctx);
int chain_index_of(const seal::SEALContext& ctx, const seal::Ciphertext& ct);

std::string sec_level_name(seal::sec_level_type level);
std::string seal_version();
std::string compression_name();

// Serialised footprint. `raw` disables compression so the number compares
// across SEAL builds; `wire` uses whatever this build defaults to.
struct Bytes {
    std::size_t raw = 0;
    std::size_t wire = 0;
};

template <typename T>
Bytes byte_size(const T& object)
{
    Bytes b;
    b.raw = static_cast<std::size_t>(object.save_size(seal::compr_mode_type::none));
    b.wire = static_cast<std::size_t>(object.save_size(seal::Serialization::compr_mode_default));
    return b;
}

// Places `v` at slot offset `slot`, zero-filling the rest of the block, and
// returns the buffer the CKKS encoder consumes.
std::vector<double> pack(const std::vector<double>& v, std::size_t slots, std::size_t slot);

} // namespace ffv

#endif // FFV_CRYPTO_HPP
