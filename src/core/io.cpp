// SPDX-License-Identifier: MIT

#include "ffv/io.hpp"

#include <sys/stat.h>
#include <sys/types.h>

#include <cerrno>
#include <cstring>
#include <fstream>
#include <sstream>

namespace ffv {

std::string join(const std::string& a, const std::string& b)
{
    if (a.empty()) return b;
    if (!a.empty() && a[a.size() - 1] == '/') return a + b;
    return a + "/" + b;
}

bool file_exists(const std::string& path)
{
    struct stat st;
    return ::stat(path.c_str(), &st) == 0;
}

std::int64_t file_size(const std::string& path)
{
    struct stat st;
    if (::stat(path.c_str(), &st) != 0) return -1;
    return static_cast<std::int64_t>(st.st_size);
}

bool make_dirs(const std::string& path, std::string& error)
{
    // Creates every missing component, the way `mkdir -p` does.
    std::string acc;
    std::size_t i = 0;
    if (!path.empty() && path[0] == '/') { acc = "/"; i = 1; }
    while (i <= path.size()) {
        const std::size_t j = path.find('/', i);
        const std::string part = path.substr(i, j == std::string::npos ? std::string::npos : j - i);
        if (!part.empty()) {
            acc = acc.empty() ? part : (acc == "/" ? "/" + part : acc + "/" + part);
            struct stat st;
            if (::stat(acc.c_str(), &st) != 0) {
                if (::mkdir(acc.c_str(), 0755) != 0 && errno != EEXIST) {
                    error = "cannot create directory " + acc + ": " + std::strerror(errno);
                    return false;
                }
            } else if (!S_ISDIR(st.st_mode)) {
                error = acc + " exists and is not a directory";
                return false;
            }
        }
        if (j == std::string::npos) break;
        i = j + 1;
    }
    return true;
}

bool write_session(const std::string& path, const Params& p, Fold f, std::string& error)
{
    std::ofstream out(path.c_str());
    if (!out) {
        error = "cannot write session descriptor " + path;
        return false;
    }
    out << "poly_modulus_degree " << p.poly_modulus_degree << "\n"
        << "scale_bits " << p.scale_bits << "\n"
        << "last_prime_bits " << p.last_prime_bits << "\n"
        << "special_prime_bits " << p.special_prime_bits << "\n"
        << "dim " << p.dim << "\n"
        << "sec_level " << sec_level_name(p.sec_level) << "\n"
        << "fold " << fold_name(f) << "\n";
    if (!out) {
        error = "write failed for " + path;
        return false;
    }
    return true;
}

bool read_session(const std::string& path, Params& p, Fold& f, std::string& error)
{
    std::ifstream in(path.c_str());
    if (!in) {
        error = "cannot read session descriptor " + path
                + "; run `ffv_client keygen` for this session first";
        return false;
    }
    std::string key, value;
    while (in >> key >> value) {
        if (key == "poly_modulus_degree") p.poly_modulus_degree = std::stoul(value);
        else if (key == "scale_bits") p.scale_bits = std::stoi(value);
        else if (key == "last_prime_bits") p.last_prime_bits = std::stoi(value);
        else if (key == "special_prime_bits") p.special_prime_bits = std::stoi(value);
        else if (key == "dim") p.dim = std::stoul(value);
        else if (key == "sec_level") {
            if (value == "tc128") p.sec_level = seal::sec_level_type::tc128;
            else if (value == "tc192") p.sec_level = seal::sec_level_type::tc192;
            else if (value == "tc256") p.sec_level = seal::sec_level_type::tc256;
            else if (value == "none") p.sec_level = seal::sec_level_type::none;
            else { error = "unknown sec_level '" + value + "' in " + path; return false; }
        } else if (key == "fold") {
            if (!parse_fold(value, f)) {
                error = "unknown fold '" + value + "' in " + path;
                return false;
            }
        }
    }
    return true;
}

} // namespace ffv
