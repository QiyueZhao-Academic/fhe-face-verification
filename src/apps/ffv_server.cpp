// SPDX-License-Identifier: MIT
//
// Server binary for the two-process protocol.
//
//   ffv_server serve --session DIR [--once] [--timeout SECONDS]
//
// This binary links the server library and the client library is absent from its
// link line, so it holds no code that can decrypt. tools/check_isolation.sh
// verifies that by reading the symbol table of the produced executable.
//
// The identifiers seal::SecretKey, seal::Decryptor, secret_key and decrypt must
// not appear anywhere in this file.

#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include <unistd.h>

#include "ffv/io.hpp"
#include "ffv/server.hpp"
#include "ffv/timing.hpp"

using namespace ffv;

namespace {

const char* kUsage =
    "ffv_server serve --session DIR [--once] [--timeout SECONDS]\n"
    "\n"
    "  --session DIR       session directory created by `ffv_client keygen`\n"
    "  --once              handle one request and exit (default)\n"
    "  --timeout SECONDS   how long to wait for a request marker (60)\n";

bool read_cleartext_template(const std::string& path, std::size_t dim, std::vector<double>& out,
                             std::string& error)
{
    std::ifstream in(path.c_str());
    if (!in) { error = "cannot read " + path; return false; }
    out.clear();
    double x = 0.0;
    while (in >> x) out.push_back(x);
    if (out.size() != dim) {
        error = path + " holds " + std::to_string(out.size()) + " values and the session expects "
                + std::to_string(dim);
        return false;
    }
    return true;
}

} // namespace

int main(int argc, char** argv)
{
    std::string session = "artifacts/session";
    int timeout_s = 60;
    if (argc < 2 || std::string(argv[1]) != "serve") {
        std::cerr << "ffv_server: the only command is `serve`\n\n" << kUsage;
        return 1;
    }
    for (int i = 2; i < argc; ++i) {
        const std::string k = argv[i];
        if (k == "--session" && i + 1 < argc) session = argv[++i];
        else if (k == "--timeout" && i + 1 < argc) timeout_s = std::atoi(argv[++i]);
        else if (k == "--once") { /* the only supported mode */ }
        else if (k == "-h" || k == "--help") { std::cout << kUsage; return 0; }
        else { std::cerr << "ffv_server: unknown or incomplete option " << k << "\n"; return 1; }
    }

    const std::string pub = join(session, "public");
    const std::string req = join(session, "request");
    const std::string rsp = join(session, "response");

    std::string error;
    Server server;
    if (!open_server(pub, server, error)) {
        std::cerr << "ffv_server: " << error << "\n";
        return 2;
    }
    std::cout << "server  : degree " << server.params.poly_modulus_degree << ", dim "
              << server.params.dim << ", " << server.params.rotation_count(server.fold)
              << " rotations per score, no decryption capability\n";

    // Wait for the client to finish writing the request. The marker file is
    // created last, so its presence means every operand is on disk.
    const std::string marker = join(req, "READY");
    int waited_ms = 0;
    while (!file_exists(marker)) {
        if (waited_ms >= timeout_s * 1000) {
            std::cerr << "ffv_server: no request appeared in " << req << " within " << timeout_s
                      << " s\n";
            return 3;
        }
        ::usleep(20000);
        waited_ms += 20;
    }

    std::string mode = "ct_ct";
    {
        std::ifstream meta(join(req, "meta.txt").c_str());
        std::string k, v;
        while (meta >> k >> v) if (k == "mode") mode = v;
    }

    seal::Ciphertext probe;
    {
        std::ifstream in(join(req, "probe.ct").c_str(), std::ios::binary);
        if (!in) { std::cerr << "ffv_server: missing " << join(req, "probe.ct") << "\n"; return 4; }
        try {
            probe.load(*server.ctx, in);
        } catch (const std::exception& e) {
            std::cerr << "ffv_server: cannot parse the probe ciphertext: " << e.what() << "\n";
            return 4;
        }
    }

    Trace trace;
    seal::Ciphertext result;
    const Timer t;
    try {
        if (mode == "ct_pt") {
            std::vector<double> enrolled;
            if (!read_cleartext_template(join(req, "enrolled.txt"), server.params.dim, enrolled,
                                         error)) {
                std::cerr << "ffv_server: " << error << "\n";
                return 5;
            }
            // Encode at the probe's scale and level so the product is well formed.
            seal::CKKSEncoder encoder(*server.ctx);
            std::vector<double> buf = pack(enrolled, encoder.slot_count(), 0);
            seal::Plaintext pt;
            encoder.encode(buf, probe.scale(), pt);
            server.eval->mod_switch_to_inplace(pt, probe.parms_id());
            result = score_ct_pt(server, probe, pt, &trace);
        } else {
            seal::Ciphertext enrolled;
            std::ifstream in(join(req, "enrolled.ct").c_str(), std::ios::binary);
            if (!in) {
                std::cerr << "ffv_server: missing " << join(req, "enrolled.ct") << "\n";
                return 5;
            }
            enrolled.load(*server.ctx, in);
            result = score_ct_ct(server, probe, enrolled, &trace);
        }
    } catch (const std::exception& e) {
        std::cerr << "ffv_server: evaluation failed: " << e.what() << "\n";
        return 6;
    }
    const double ms = t.ms();

    if (!make_dirs(rsp, error)) {
        std::cerr << "ffv_server: " << error << "\n";
        return 7;
    }
    {
        std::ofstream out(join(rsp, "score.ct").c_str(), std::ios::binary);
        if (!out) { std::cerr << "ffv_server: cannot write the response\n"; return 7; }
        result.save(out);
    }
    {
        std::ofstream meta(join(rsp, "meta.txt").c_str());
        meta << "mode " << mode << "\nserver_score_ms " << ms << "\nrotations " << trace.rotations
             << "\nchain_index_out " << trace.level_out << "\n";
    }
    std::ofstream(join(rsp, "DONE").c_str()) << "1\n";

    std::cout << "evaluate: " << ms << " ms (" << trace.rotations << " rotations, multiply "
              << trace.ms_multiply << " ms, fold " << trace.ms_fold << " ms), result written to "
              << join(rsp, "score.ct") << "\n";
    return 0;
}
