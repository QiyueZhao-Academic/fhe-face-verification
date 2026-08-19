// SPDX-License-Identifier: MIT
//
// Server side: the half that is trusted for availability and untrusted for
// confidentiality. This header and src/core/server.cpp are compiled into a
// library that the client binary does not link, and the identifiers
//
//     seal::SecretKey    seal::Decryptor    secret_key    decrypt
//
// appear nowhere in it. tools/check_isolation.sh enforces that by grepping the
// sources and by reading the linked binary's symbol table.

#ifndef FFV_SERVER_HPP
#define FFV_SERVER_HPP

#include <memory>
#include <string>

#include "ffv/crypto.hpp"

namespace ffv {

// Everything the evaluator is allowed to hold.
struct Server {
    Params params;
    Fold fold = Fold::Log2;
    std::shared_ptr<seal::SEALContext> ctx;
    seal::RelinKeys relin_keys;
    seal::GaloisKeys galois_keys;
    std::unique_ptr<seal::Evaluator> eval;
};

// Loads the session descriptor and the evaluation keys from `pub_dir`.
bool open_server(const std::string& pub_dir, Server& out, std::string& error);

// Builds a server directly from an in-process key set, for the benchmark path
// where spawning a second process would only add noise to the timings.
bool attach_server(const Params& p, Fold f, std::shared_ptr<seal::SEALContext> ctx,
                   const seal::RelinKeys& rk, const seal::GaloisKeys& gk, Server& out,
                   std::string& error);

// Per-call diagnostics, so the depth and rescale behaviour the report claims is
// measured on the spot.
struct Trace {
    int rotations = 0;
    int level_in = 0;
    int level_after_mul = 0;
    int level_out = 0;
    double scale_in = 0.0;
    double scale_after_mul = 0.0;
    double scale_out = 0.0;
    double ms_multiply = 0.0;
    double ms_relinearize = 0.0;
    double ms_rescale = 0.0;
    double ms_fold = 0.0;
    double ms_total = 0.0;
};

// Homomorphic cosine similarity of two encrypted templates.
//
//   multiply -> relinearize -> rescale -> rotate-and-sum fold
//
// Multiplicative depth is one, so no bootstrapping is involved. On return, the
// score of batch member k occupies slot k * block(); every other slot holds a
// partial sum.
seal::Ciphertext score_ct_ct(Server& s, const seal::Ciphertext& a, const seal::Ciphertext& b,
                             Trace* trace);

// Same circuit with the enrolled template in the clear: the plaintext multiply
// skips relinearization, which removes one key-switch from the critical path.
seal::Ciphertext score_ct_pt(Server& s, const seal::Ciphertext& a, const seal::Plaintext& b,
                             Trace* trace);

} // namespace ffv

#endif // FFV_SERVER_HPP
