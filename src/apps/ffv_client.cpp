// SPDX-License-Identifier: MIT
//
// Client binary for the two-process protocol.
//
//   ffv_client keygen  --session DIR
//   ffv_client request --session DIR --templates FILE --pair K
//   ffv_client collect --session DIR --templates FILE --pair K [--threshold T]
//
// The three steps are separate invocations so that the server runs as its own
// process against files on disk. The secret key is written to DIR/private and is
// read by this binary only; DIR/public holds the evaluation keys the server
// needs, and DIR/request and DIR/response hold the wire traffic. Byte counts in
// the summary are the sizes of those files, so the bandwidth the report quotes is
// the bandwidth that actually crossed the boundary.

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>

#include "ffv/client.hpp"
#include "ffv/io.hpp"
#include "ffv/json.hpp"
#include "ffv/templates.hpp"
#include "ffv/timing.hpp"

using namespace ffv;

namespace {

struct Args {
    std::string command;
    std::string session = "artifacts/session";
    std::string templates;
    int pair = 0;
    double threshold = 0.0;
    bool have_threshold = false;
    std::size_t degree = 8192;
    int scale_bits = 40;
    std::string mode = "ct_ct";
};

const char* kUsage =
    "ffv_client COMMAND [options]\n"
    "\n"
    "  keygen   --session DIR [--degree N] [--scale-bits N]\n"
    "  request  --session DIR --templates FILE --pair K [--mode ct_ct|ct_pt]\n"
    "  collect  --session DIR --templates FILE --pair K [--threshold T]\n";

bool parse(int argc, char** argv, Args& a, std::string& error)
{
    if (argc < 2) {
        error = std::string("a command is required\n\n") + kUsage;
        return false;
    }
    a.command = argv[1];
    for (int i = 2; i < argc; ++i) {
        const std::string k = argv[i];
        const bool has_next = i + 1 < argc;
        if (k == "--session" && has_next) a.session = argv[++i];
        else if (k == "--templates" && has_next) a.templates = argv[++i];
        else if (k == "--pair" && has_next) a.pair = std::atoi(argv[++i]);
        else if (k == "--threshold" && has_next) { a.threshold = std::atof(argv[++i]); a.have_threshold = true; }
        else if (k == "--degree" && has_next) a.degree = static_cast<std::size_t>(std::atol(argv[++i]));
        else if (k == "--scale-bits" && has_next) a.scale_bits = std::atoi(argv[++i]);
        else if (k == "--mode" && has_next) a.mode = argv[++i];
        else if (k == "-h" || k == "--help") { std::cout << kUsage; std::exit(0); }
        else { error = "unknown or incomplete option " + k + "\n\n" + kUsage; return false; }
    }
    return true;
}

std::string pub_dir(const Args& a) { return join(a.session, "public"); }
std::string sec_dir(const Args& a) { return join(a.session, "private"); }
std::string req_dir(const Args& a) { return join(a.session, "request"); }
std::string rsp_dir(const Args& a) { return join(a.session, "response"); }

template <typename T>
bool write_object(const T& object, const std::string& path, std::string& error)
{
    std::ofstream out(path.c_str(), std::ios::binary);
    if (!out) { error = "cannot write " + path; return false; }
    object.save(out);
    return static_cast<bool>(out);
}

bool load_pair(const Args& a, Pair& pair, TemplateSet& set, std::string& error)
{
    if (a.templates.empty()) {
        error = "--templates is required for this command";
        return false;
    }
    if (!load_templates(a.templates, set, error)) return false;
    if (a.pair < 0 || static_cast<std::size_t>(a.pair) >= set.pairs.size()) {
        error = "--pair " + std::to_string(a.pair) + " is outside 0.."
                + std::to_string(set.pairs.size() - 1);
        return false;
    }
    pair = set.pairs[static_cast<std::size_t>(a.pair)];
    return true;
}

int do_keygen(const Args& a)
{
    Params p;
    p.poly_modulus_degree = a.degree;
    p.scale_bits = a.scale_bits;
    std::string error;
    Client c;
    if (!c.init(p, Fold::Log2, error)) {
        std::cerr << "ffv_client: " << error << "\n";
        return 2;
    }
    if (!c.save(pub_dir(a), sec_dir(a), error)) {
        std::cerr << "ffv_client: " << error << "\n";
        return 3;
    }
    const KeySizes ks = c.key_sizes();
    std::cout << "keygen  : " << c.keygen_ms() << " ms\n"
              << "public  : " << pub_dir(a) << " (relin " << ks.relin_keys.wire
              << " B, galois " << ks.galois_keys.wire << " B over " << ks.galois_steps
              << " strides)\n"
              << "private : " << sec_dir(a) << " (secret key " << ks.secret_key.wire << " B)\n";
    return 0;
}

int do_request(const Args& a)
{
    std::string error;
    Client c;
    if (!c.load(pub_dir(a), sec_dir(a), error)) {
        std::cerr << "ffv_client: " << error << "\n";
        return 2;
    }
    Pair pair;
    TemplateSet set;
    if (!load_pair(a, pair, set, error)) {
        std::cerr << "ffv_client: " << error << "\n";
        return 3;
    }
    if (set.dim != c.params().dim) {
        std::cerr << "ffv_client: the session was created for dimension " << c.params().dim
                  << " and this container holds dimension " << set.dim
                  << "; regenerate keys with --degree matched to the container\n";
        return 4;
    }
    if (!make_dirs(req_dir(a), error) || !make_dirs(rsp_dir(a), error)) {
        std::cerr << "ffv_client: " << error << "\n";
        return 5;
    }
    // A stale response from an earlier request would otherwise be collected.
    std::remove(join(rsp_dir(a), "score.ct").c_str());
    std::remove(join(rsp_dir(a), "DONE").c_str());

    const Timer t;
    const seal::Ciphertext probe = c.encrypt(pair.a);
    if (!write_object(probe, join(req_dir(a), "probe.ct"), error)) {
        std::cerr << "ffv_client: " << error << "\n";
        return 6;
    }
    if (a.mode == "ct_pt") {
        // The enrolled template travels in the clear in this mode.
        std::ofstream out(join(req_dir(a), "enrolled.txt").c_str());
        out.precision(17);
        for (double x : pair.b) out << x << "\n";
    } else {
        const seal::Ciphertext enrolled = c.encrypt(pair.b);
        if (!write_object(enrolled, join(req_dir(a), "enrolled.ct"), error)) {
            std::cerr << "ffv_client: " << error << "\n";
            return 6;
        }
    }
    {
        std::ofstream meta(join(req_dir(a), "meta.txt").c_str());
        meta << "mode " << a.mode << "\npair " << a.pair << "\nclient_encrypt_ms " << t.ms()
             << "\n";
    }
    // The marker is written last, so its presence means the request is complete.
    std::ofstream(join(req_dir(a), "READY").c_str()) << "1\n";

    std::cout << "request : pair " << a.pair << " (" << (pair.genuine ? "genuine" : "impostor")
              << "), mode " << a.mode << ", " << t.ms() << " ms to encrypt\n";
    return 0;
}

int do_collect(const Args& a)
{
    std::string error;
    Client c;
    if (!c.load(pub_dir(a), sec_dir(a), error)) {
        std::cerr << "ffv_client: " << error << "\n";
        return 2;
    }
    const std::string score_path = join(rsp_dir(a), "score.ct");
    if (!file_exists(join(rsp_dir(a), "DONE")) || !file_exists(score_path)) {
        std::cerr << "ffv_client: no completed response in " << rsp_dir(a)
                  << "; run `ffv_server serve --session " << a.session << " --once` first\n";
        return 3;
    }
    Pair pair;
    TemplateSet set;
    if (!load_pair(a, pair, set, error)) {
        std::cerr << "ffv_client: " << error << "\n";
        return 4;
    }

    seal::Ciphertext result;
    {
        std::ifstream in(score_path.c_str(), std::ios::binary);
        try {
            result.load(c.context(), in);
        } catch (const std::exception& e) {
            std::cerr << "ffv_client: cannot parse " << score_path << ": " << e.what() << "\n";
            return 5;
        }
    }
    const Timer t;
    const double score = c.read_score(result, 0);
    const double decrypt_ms = t.ms();
    const double reference = cosine(pair.a, pair.b);

    // Read whatever the server recorded about its own work.
    double server_ms = 0.0;
    std::string mode = "ct_ct";
    {
        std::ifstream in(join(rsp_dir(a), "meta.txt").c_str());
        std::string k, v;
        while (in >> k >> v) {
            if (k == "server_score_ms") server_ms = std::atof(v.c_str());
            else if (k == "mode") mode = v;
        }
    }
    const std::int64_t up_probe = file_size(join(req_dir(a), "probe.ct"));
    const std::int64_t up_enrolled = file_size(join(req_dir(a), "enrolled.ct"));
    const std::int64_t down = file_size(score_path);

    const bool accept = a.have_threshold ? (score >= a.threshold) : false;
    std::cout.precision(10);
    std::cout << "collect : score " << score << " (cleartext reference " << reference
              << ", |error| " << std::fabs(score - reference) << ")\n";
    if (a.have_threshold) {
        std::cout << "decision: " << (accept ? "accept" : "reject") << " at threshold "
                  << a.threshold << ", margin " << std::fabs(reference - a.threshold)
                  << ", truth " << (pair.genuine ? "genuine" : "impostor") << "\n";
    }
    std::cout << "traffic : uplink " << (up_probe < 0 ? 0 : up_probe)
              << (up_enrolled > 0 ? " + " + std::to_string(up_enrolled) : std::string())
              << " B, downlink " << (down < 0 ? 0 : down) << " B\n";

    // A machine-readable record of the round trip for the report.
    std::ofstream out(join(a.session, "protocol.json").c_str());
    if (out) {
        Json j(out);
        j.begin_object();
        j.key_string("schema", "ffv-protocol-1");
        j.key_string("mode", mode);
        j.key_int("pair_index", a.pair);
        j.key_bool("pair_genuine", pair.genuine);
        j.key_double("score_encrypted", score);
        j.key_double("score_cleartext", reference);
        j.key_double("abs_error", std::fabs(score - reference));
        j.key_double("server_score_ms", server_ms);
        j.key_double("client_decrypt_ms", decrypt_ms);
        j.key_int("uplink_probe_bytes", up_probe < 0 ? 0 : up_probe);
        j.key_int("uplink_enrolled_bytes", up_enrolled < 0 ? 0 : up_enrolled);
        j.key_int("downlink_bytes", down < 0 ? 0 : down);
        if (a.have_threshold) {
            j.key_double("threshold", a.threshold);
            j.key_bool("accept", accept);
            j.key_bool("decision_matches_truth", accept == pair.genuine);
        }
        j.end_object();
        out << "\n";
    }
    return 0;
}

} // namespace

int main(int argc, char** argv)
{
    Args a;
    std::string error;
    if (!parse(argc, argv, a, error)) {
        std::cerr << "ffv_client: " << error << "\n";
        return 1;
    }
    if (a.command == "keygen") return do_keygen(a);
    if (a.command == "request") return do_request(a);
    if (a.command == "collect") return do_collect(a);
    std::cerr << "ffv_client: unknown command '" << a.command << "'\n\n" << kUsage;
    return 1;
}
