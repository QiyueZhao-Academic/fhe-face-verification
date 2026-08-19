// SPDX-License-Identifier: MIT

#include "ffv/templates.hpp"

#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>

namespace ffv {

namespace {

bool read_exact(std::istream& in, void* dst, std::size_t n)
{
    in.read(static_cast<char*>(dst), static_cast<std::streamsize>(n));
    return static_cast<std::size_t>(in.gcount()) == n;
}

bool little_endian()
{
    const std::uint32_t x = 1;
    unsigned char b[4];
    std::memcpy(b, &x, 4);
    return b[0] == 1;
}

} // namespace

int TemplateSet::genuine_count() const
{
    int n = 0;
    for (const Pair& p : pairs) if (p.genuine) ++n;
    return n;
}

int TemplateSet::impostor_count() const { return static_cast<int>(pairs.size()) - genuine_count(); }

double TemplateSet::max_norm_error() const
{
    double worst = 0.0;
    for (const Pair& p : pairs) {
        for (int which = 0; which < 2; ++which) {
            const std::vector<double>& v = which == 0 ? p.a : p.b;
            double s = 0.0;
            for (double x : v) s += x * x;
            const double e = std::fabs(std::sqrt(s) - 1.0);
            if (e > worst) worst = e;
        }
    }
    return worst;
}

bool load_templates(const std::string& path, TemplateSet& out, std::string& error)
{
    if (!little_endian()) {
        error = "the .ffvemb container is little-endian and this host is big-endian";
        return false;
    }
    std::ifstream in(path.c_str(), std::ios::binary);
    if (!in) {
        error = "cannot open template file " + path
                + "; run `python3 python/extract_embeddings.py` to build it";
        return false;
    }

    char magic[8];
    if (!read_exact(in, magic, 8) || std::memcmp(magic, "FFVEMB03", 8) != 0) {
        error = path + " is not an FFVEMB03 container";
        return false;
    }
    std::uint32_t dim = 0, n_pairs = 0, n_folds = 0, flags = 0, len_source = 0, len_desc = 0;
    if (!read_exact(in, &dim, 4) || !read_exact(in, &n_pairs, 4) || !read_exact(in, &n_folds, 4)
        || !read_exact(in, &flags, 4) || !read_exact(in, &len_source, 4)
        || !read_exact(in, &len_desc, 4)) {
        error = path + " has a truncated header";
        return false;
    }
    if (dim == 0 || dim > (1u << 20)) {
        error = path + " declares an implausible dimension " + std::to_string(dim);
        return false;
    }
    std::string source(len_source, '\0'), desc(len_desc, '\0');
    if (len_source && !read_exact(in, &source[0], len_source)) {
        error = path + " has a truncated source string";
        return false;
    }
    if (len_desc && !read_exact(in, &desc[0], len_desc)) {
        error = path + " has a truncated description string";
        return false;
    }

    out.dim = dim;
    out.folds = static_cast<int>(n_folds);
    out.real_faces = (flags & 1u) != 0;
    out.source = source;
    out.description = desc;
    out.pairs.clear();
    out.pairs.reserve(n_pairs);

    std::vector<float> buf(dim);
    for (std::uint32_t k = 0; k < n_pairs; ++k) {
        Pair p;
        p.a.resize(dim);
        p.b.resize(dim);
        for (int which = 0; which < 2; ++which) {
            if (!read_exact(in, buf.data(), dim * sizeof(float))) {
                error = path + " ends after " + std::to_string(k) + " of "
                        + std::to_string(n_pairs) + " pairs";
                return false;
            }
            std::vector<double>& dst = which == 0 ? p.a : p.b;
            for (std::uint32_t i = 0; i < dim; ++i) dst[i] = static_cast<double>(buf[i]);
        }
        std::uint8_t label = 0, padding = 0;
        std::uint16_t fold = 0;
        if (!read_exact(in, &label, 1) || !read_exact(in, &fold, 2)
            || !read_exact(in, &padding, 1)) {
            error = path + " has a truncated pair record at index " + std::to_string(k);
            return false;
        }
        p.genuine = label != 0;
        p.fold = static_cast<int>(fold);
        out.pairs.push_back(std::move(p));
    }

    if (out.pairs.empty()) {
        error = path + " holds no pairs";
        return false;
    }
    if (out.genuine_count() == 0 || out.impostor_count() == 0) {
        error = path + " holds only one class, so no threshold can be fitted";
        return false;
    }
    if (out.folds <= 0) out.folds = 1;
    return true;
}

} // namespace ffv
