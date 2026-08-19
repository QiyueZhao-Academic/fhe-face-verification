// SPDX-License-Identifier: MIT

#include "ffv/client.hpp"

#include <fstream>
#include <stdexcept>

#include "ffv/io.hpp"
#include "ffv/timing.hpp"

namespace ffv {

namespace {

// File names inside a session directory. Both processes agree on these.
const char* kSession = "session.txt";
const char* kPublic = "public.key";
const char* kRelin = "relin.key";
const char* kGalois = "galois.key";
const char* kSecret = "secret.key";

template <typename T>
bool save_to(const T& object, const std::string& path, std::string& error)
{
    std::ofstream out(path.c_str(), std::ios::binary);
    if (!out) {
        error = "cannot open " + path + " for writing";
        return false;
    }
    object.save(out);
    if (!out) {
        error = "write failed for " + path;
        return false;
    }
    return true;
}

template <typename T>
bool load_from(T& object, const seal::SEALContext& ctx, const std::string& path,
               std::string& error)
{
    std::ifstream in(path.c_str(), std::ios::binary);
    if (!in) {
        error = "cannot open " + path + " for reading";
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

} // namespace

double cosine(const std::vector<double>& a, const std::vector<double>& b)
{
    const std::size_t n = a.size() < b.size() ? a.size() : b.size();
    double s = 0.0;
    for (std::size_t i = 0; i < n; ++i) s += a[i] * b[i];
    return s;
}

bool Client::init(const Params& p, Fold f, std::string& error)
{
    p_ = p;
    fold_ = f;
    ctx_ = make_context(p_, error);
    if (!ctx_) return false;

    steps_ = p_.rotation_steps(fold_);
    const Timer t;
    try {
        seal::KeyGenerator kg(*ctx_);
        sk_ = std::make_unique<seal::SecretKey>(kg.secret_key());
        pk_ = std::make_unique<seal::PublicKey>();
        kg.create_public_key(*pk_);
        rk_ = std::make_unique<seal::RelinKeys>();
        kg.create_relin_keys(*rk_);
        gk_ = std::make_unique<seal::GaloisKeys>();
        // Only the strides the fold actually uses, which keeps the Galois key
        // an order of magnitude smaller than the all-rotations default.
        kg.create_galois_keys(steps_, *gk_);
    } catch (const std::exception& e) {
        error = std::string("key generation failed: ") + e.what();
        return false;
    }
    keygen_ms_ = t.ms();

    enc_ = std::make_unique<seal::Encryptor>(*ctx_, *pk_);
    dec_ = std::make_unique<seal::Decryptor>(*ctx_, *sk_);
    cod_ = std::make_unique<seal::CKKSEncoder>(*ctx_);
    return true;
}

bool Client::save(const std::string& pub_dir, const std::string& sec_dir,
                  std::string& error) const
{
    if (!make_dirs(pub_dir, error) || !make_dirs(sec_dir, error)) return false;
    if (!write_session(join(pub_dir, kSession), p_, fold_, error)) return false;
    if (!save_to(*pk_, join(pub_dir, kPublic), error)) return false;
    if (!save_to(*rk_, join(pub_dir, kRelin), error)) return false;
    if (!save_to(*gk_, join(pub_dir, kGalois), error)) return false;
    // The secret key is the only object written outside pub_dir.
    return save_to(*sk_, join(sec_dir, kSecret), error);
}

bool Client::load(const std::string& pub_dir, const std::string& sec_dir, std::string& error)
{
    if (!read_session(join(pub_dir, kSession), p_, fold_, error)) return false;
    ctx_ = make_context(p_, error);
    if (!ctx_) return false;
    steps_ = p_.rotation_steps(fold_);

    pk_ = std::make_unique<seal::PublicKey>();
    rk_ = std::make_unique<seal::RelinKeys>();
    gk_ = std::make_unique<seal::GaloisKeys>();
    sk_ = std::make_unique<seal::SecretKey>();
    if (!load_from(*pk_, *ctx_, join(pub_dir, kPublic), error)) return false;
    if (!load_from(*rk_, *ctx_, join(pub_dir, kRelin), error)) return false;
    if (!load_from(*gk_, *ctx_, join(pub_dir, kGalois), error)) return false;
    if (!load_from(*sk_, *ctx_, join(sec_dir, kSecret), error)) return false;

    enc_ = std::make_unique<seal::Encryptor>(*ctx_, *pk_);
    dec_ = std::make_unique<seal::Decryptor>(*ctx_, *sk_);
    cod_ = std::make_unique<seal::CKKSEncoder>(*ctx_);
    return true;
}

seal::Ciphertext Client::encrypt(const std::vector<double>& v, std::size_t slot) const
{
    const std::vector<double> buf =
        pack(v, cod_->slot_count(), slot * p_.block());
    seal::Plaintext pt;
    cod_->encode(buf, p_.scale(), pt);
    seal::Ciphertext ct;
    enc_->encrypt(pt, ct);
    return ct;
}

seal::Ciphertext Client::encrypt_batch(const std::vector<std::vector<double>>& vs) const
{
    const std::size_t slots = cod_->slot_count();
    const std::size_t blk = p_.block();
    if (vs.size() * blk > slots) {
        throw std::invalid_argument("batch of " + std::to_string(vs.size())
                                    + " templates does not fit in " + std::to_string(slots)
                                    + " slots");
    }
    std::vector<double> buf(slots, 0.0);
    for (std::size_t k = 0; k < vs.size(); ++k) {
        for (std::size_t i = 0; i < vs[k].size() && i < blk; ++i) buf[k * blk + i] = vs[k][i];
    }
    seal::Plaintext pt;
    cod_->encode(buf, p_.scale(), pt);
    seal::Ciphertext ct;
    enc_->encrypt(pt, ct);
    return ct;
}

seal::Plaintext Client::encode_at(const std::vector<double>& v, const seal::Ciphertext& like,
                                 std::size_t slot) const
{
    const std::vector<double> buf = pack(v, cod_->slot_count(), slot * p_.block());
    seal::Plaintext pt;
    cod_->encode(buf, like.scale(), pt);
    // A plaintext multiplicand must sit at the ciphertext's level.
    seal::Evaluator ev(*ctx_);
    ev.mod_switch_to_inplace(pt, like.parms_id());
    return pt;
}

seal::Plaintext Client::encode_batch_at(const std::vector<std::vector<double>>& vs,
                                       const seal::Ciphertext& like) const
{
    const std::size_t slots = cod_->slot_count();
    const std::size_t blk = p_.block();
    if (vs.size() * blk > slots) {
        throw std::invalid_argument("batch of " + std::to_string(vs.size())
                                    + " templates does not fit in " + std::to_string(slots)
                                    + " slots");
    }
    std::vector<double> buf(slots, 0.0);
    for (std::size_t k = 0; k < vs.size(); ++k) {
        for (std::size_t i = 0; i < vs[k].size() && i < blk; ++i) buf[k * blk + i] = vs[k][i];
    }
    seal::Plaintext pt;
    cod_->encode(buf, like.scale(), pt);
    seal::Evaluator ev(*ctx_);
    ev.mod_switch_to_inplace(pt, like.parms_id());
    return pt;
}

double Client::read_score(const seal::Ciphertext& ct, std::size_t slot) const
{
    return read_scores(ct, slot + 1)[slot];
}

std::vector<double> Client::read_scores(const seal::Ciphertext& ct, std::size_t count) const
{
    seal::Plaintext pt;
    dec_->decrypt(ct, pt);
    std::vector<double> all;
    cod_->decode(pt, all);
    // After the fold, the score of batch member k sits at the first slot of its
    // block; every other slot holds a partial sum with no meaning here.
    std::vector<double> out(count, 0.0);
    for (std::size_t k = 0; k < count; ++k) {
        const std::size_t idx = k * p_.block();
        if (idx < all.size()) out[k] = all[idx];
    }
    return out;
}

KeySizes Client::key_sizes() const
{
    KeySizes s;
    s.public_key = byte_size(*pk_);
    s.relin_keys = byte_size(*rk_);
    s.galois_keys = byte_size(*gk_);
    s.secret_key = byte_size(*sk_);
    s.galois_steps = static_cast<int>(steps_.size());
    return s;
}

} // namespace ffv
