// SPDX-License-Identifier: MIT
//
// Client side. The secret key lives here and in no other translation unit.

#ifndef FFV_CLIENT_HPP
#define FFV_CLIENT_HPP

#include <memory>
#include <string>
#include <vector>

#include "ffv/crypto.hpp"

namespace ffv {

struct KeySizes {
    Bytes public_key;
    Bytes relin_keys;
    Bytes galois_keys;
    Bytes secret_key;
    int galois_steps = 0;
};

class Client {
public:
    // Builds the context and a fresh key set. Returns false with `error` set.
    bool init(const Params& p, Fold f, std::string& error);

    // Re-opens a session: parameters and public keys from `pub_dir`, secret key
    // from `sec_dir`.
    bool load(const std::string& pub_dir, const std::string& sec_dir, std::string& error);

    // Writes evaluation keys to `pub_dir` and the secret key to `sec_dir`.
    bool save(const std::string& pub_dir, const std::string& sec_dir, std::string& error) const;

    // Encrypts one L2-normalised template into slot `slot * block`.
    seal::Ciphertext encrypt(const std::vector<double>& v, std::size_t slot = 0) const;

    // Encrypts up to max_batch() templates side by side in one ciphertext.
    seal::Ciphertext encrypt_batch(const std::vector<std::vector<double>>& vs) const;

    // Reads the score of batch member `slot` out of a folded result.
    double read_score(const seal::Ciphertext& ct, std::size_t slot = 0) const;
    std::vector<double> read_scores(const seal::Ciphertext& ct, std::size_t count) const;

    // Encodes a template for the ct x pt mode, matched to `like`'s level.
    seal::Plaintext encode_at(const std::vector<double>& v, const seal::Ciphertext& like,
                              std::size_t slot = 0) const;
    seal::Plaintext encode_batch_at(const std::vector<std::vector<double>>& vs,
                                    const seal::Ciphertext& like) const;

    const seal::SEALContext& context() const { return *ctx_; }
    std::shared_ptr<seal::SEALContext> context_ptr() const { return ctx_; }
    const Params& params() const { return p_; }
    Fold fold() const { return fold_; }
    const seal::RelinKeys& relin_keys() const { return *rk_; }
    const seal::GaloisKeys& galois_keys() const { return *gk_; }
    KeySizes key_sizes() const;
    double keygen_ms() const { return keygen_ms_; }

private:
    Params p_;
    Fold fold_ = Fold::Log2;
    std::vector<int> steps_;
    std::shared_ptr<seal::SEALContext> ctx_;
    std::unique_ptr<seal::SecretKey> sk_;
    std::unique_ptr<seal::PublicKey> pk_;
    std::unique_ptr<seal::RelinKeys> rk_;
    std::unique_ptr<seal::GaloisKeys> gk_;
    std::unique_ptr<seal::Encryptor> enc_;
    std::unique_ptr<seal::Decryptor> dec_;
    std::unique_ptr<seal::CKKSEncoder> cod_;
    double keygen_ms_ = 0.0;
};

// Plaintext reference score. Both operands are expected to be L2-normalised,
// which makes this the cosine similarity.
double cosine(const std::vector<double>& a, const std::vector<double>& b);

} // namespace ffv

#endif // FFV_CLIENT_HPP
