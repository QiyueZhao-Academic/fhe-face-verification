// ckks_dot.cpp -- homomorphic inner product of face embeddings under CKKS.
//
// Protocol implemented (semi-honest server, single-key setting):
//   1. Client generates the CKKS keys and encrypts both L2-normalised templates.
//   2. Server multiplies the two ciphertexts, relinearises, rescales, then
//      folds all slots with a rotate-and-add reduction: log2(slot_count)
//      rotations turn the coefficient-wise product into its total sum.
//   3. Client decrypts slot 0 only, obtaining the cosine similarity.
//
// The server never sees a plaintext template and never sees the score.
//
// Parameters: N (poly_modulus_degree) with a [60, scale_bits, 60] modulus
// chain. For N = 8192 this is 160 bits total, under the 218-bit ceiling for
// 128-bit security, so SEAL's tc128 level is satisfied. Multiplicative depth
// used is 1, hence no bootstrapping.

#include <seal/seal.h>
#include <nlohmann/json.hpp>

#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

using json = nlohmann::json;
using namespace seal;
using Clock = std::chrono::steady_clock;

static double ms_since(const Clock::time_point &t0) {
  return std::chrono::duration<double, std::milli>(Clock::now() - t0).count();
}

static void usage() {
  std::cerr << "usage: ckks_dot bench --in pairs.json --out result.json "
               "[--poly 8192] [--scale-bits 40]\n"
               "       ckks_dot --version\n";
}

int main(int argc, char **argv) {
  std::string in_path, out_path;
  std::size_t poly = 8192;
  int scale_bits = 40;

  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    auto next = [&]() -> std::string {
      if (i + 1 >= argc) { usage(); std::exit(2); }
      return std::string(argv[++i]);
    };
    if (arg == "bench") continue;
    else if (arg == "--in") in_path = next();
    else if (arg == "--out") out_path = next();
    else if (arg == "--poly") poly = static_cast<std::size_t>(std::stoul(next()));
    else if (arg == "--scale-bits") scale_bits = std::stoi(next());
    else if (arg == "--version") { std::cout << "ckks_dot 0.1.0 (SEAL " << SEAL_VERSION << ")\n"; return 0; }
    else { usage(); return 2; }
  }
  if (in_path.empty() || out_path.empty()) { usage(); return 2; }

  // ---- load the batch of pairs -------------------------------------------
  json input;
  { std::ifstream fin(in_path);
    if (!fin) { std::cerr << "cannot open " << in_path << "\n"; return 1; }
    fin >> input; }
  const auto A = input.at("a").get<std::vector<std::vector<double>>>();
  const auto B = input.at("b").get<std::vector<std::vector<double>>>();
  if (A.size() != B.size() || A.empty()) { std::cerr << "invalid input batch\n"; return 1; }
  const std::size_t n = A.size();
  const std::size_t dim = A[0].size();

  // ---- key generation (client) -------------------------------------------
  auto t0 = Clock::now();
  EncryptionParameters parms(scheme_type::ckks);
  parms.set_poly_modulus_degree(poly);
  parms.set_coeff_modulus(CoeffModulus::Create(poly, {60, scale_bits, 60}));
  SEALContext context(parms, true, sec_level_type::tc128);

  KeyGenerator keygen(context);
  SecretKey secret_key = keygen.secret_key();
  PublicKey public_key;   keygen.create_public_key(public_key);
  RelinKeys relin_keys;   keygen.create_relin_keys(relin_keys);

  CKKSEncoder encoder(context);
  const std::size_t slot_count = encoder.slot_count();
  if (dim > slot_count) { std::cerr << "dim exceeds slot count\n"; return 1; }

  // Only power-of-two rotations are needed for the fold, which keeps the
  // Galois key material small compared to create_galois_keys() with all steps.
  std::vector<int> steps;
  for (std::size_t s = 1; s < slot_count; s <<= 1) steps.push_back(static_cast<int>(s));
  GaloisKeys galois_keys; keygen.create_galois_keys(steps, galois_keys);
  const double keygen_ms = ms_since(t0);

  Encryptor encryptor(context, public_key);
  Evaluator evaluator(context);
  Decryptor decryptor(context, secret_key);
  const double scale = std::pow(2.0, scale_bits);

  // ---- encryption (client) ------------------------------------------------
  t0 = Clock::now();
  std::vector<Ciphertext> ca(n), cb(n);
  for (std::size_t i = 0; i < n; ++i) {
    Plaintext pa, pb;
    encoder.encode(A[i], scale, pa);
    encoder.encode(B[i], scale, pb);
    encryptor.encrypt(pa, ca[i]);
    encryptor.encrypt(pb, cb[i]);
  }
  const double encrypt_ms = ms_since(t0);

  std::size_t ct_bytes = 0, gk_bytes = 0;
  { std::stringstream ss; ct_bytes = static_cast<std::size_t>(ca[0].save(ss)); }
  { std::stringstream ss; gk_bytes = static_cast<std::size_t>(galois_keys.save(ss)); }

  // ---- homomorphic inner product (server) --------------------------------
  t0 = Clock::now();
  std::vector<Ciphertext> cs(n);
  for (std::size_t i = 0; i < n; ++i) {
    Ciphertext prod;
    evaluator.multiply(ca[i], cb[i], prod);
    evaluator.relinearize_inplace(prod, relin_keys);
    evaluator.rescale_to_next_inplace(prod);
    // Rotate-and-add fold: after log2(slot_count) steps every slot holds the
    // sum of all slots; unused slots are zero, so this is exactly the dot product.
    for (int s : steps) {
      Ciphertext rotated;
      evaluator.rotate_vector(prod, s, galois_keys, rotated);
      evaluator.add_inplace(prod, rotated);
    }
    cs[i] = std::move(prod);
  }
  const double dot_ms = ms_since(t0);

  // ---- decryption of the score only (client) -----------------------------
  t0 = Clock::now();
  std::vector<double> scores(n);
  for (std::size_t i = 0; i < n; ++i) {
    Plaintext pt;
    decryptor.decrypt(cs[i], pt);
    std::vector<double> decoded;
    encoder.decode(pt, decoded);
    scores[i] = decoded[0];
  }
  const double decrypt_ms = ms_since(t0);

  // ---- report -------------------------------------------------------------
  json out;
  out["scores"] = scores;
  out["timings"] = {
      {"keygen_ms", keygen_ms},
      {"encrypt_ms_per_vector", encrypt_ms / static_cast<double>(2 * n)},
      {"dot_ms_per_pair", dot_ms / static_cast<double>(n)},
      {"decrypt_ms_per_pair", decrypt_ms / static_cast<double>(n)},
  };
  out["ct_size_bytes"] = ct_bytes;
  out["galois_keys_bytes"] = gk_bytes;
  out["params"] = {
      {"scheme", "CKKS"},
      {"poly_modulus_degree", poly},
      {"coeff_mod_bit_sizes", json::array({60, scale_bits, 60})},
      {"scale_bits", scale_bits},
      {"slot_count", slot_count},
      {"security_level_bits", 128},
      {"rotations_per_pair", steps.size()},
      {"seal_version", SEAL_VERSION},
  };

  std::ofstream fout(out_path);
  if (!fout) { std::cerr << "cannot write " << out_path << "\n"; return 1; }
  fout << out.dump(2) << std::endl;
  return 0;
}
