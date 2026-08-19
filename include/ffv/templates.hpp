// SPDX-License-Identifier: MIT
//
// Reader for the .ffvemb container that the Python frontend writes.
//
// Layout, little-endian throughout:
//
//   magic      8   "FFVEMB03"
//   dim        u32 template dimension
//   n_pairs    u32
//   n_folds    u32 folds defined by the evaluation protocol
//   flags      u32 bit 0 set when the templates come from real photographs
//   len_source u32
//   len_desc   u32
//   source     len_source bytes, a short identifier such as "lfw-w600k_r50"
//   desc       len_desc bytes, free-form provenance recorded in the report
//   n_pairs records of:
//       a      dim float32
//       b      dim float32
//       label  u8    1 for a genuine pair, 0 for an impostor pair
//       fold   u16   zero-based fold index
//       pad    u8

#ifndef FFV_TEMPLATES_HPP
#define FFV_TEMPLATES_HPP

#include <cstddef>
#include <string>
#include <vector>

namespace ffv {

struct Pair {
    std::vector<double> a;
    std::vector<double> b;
    bool genuine = false;
    int fold = 0;
};

struct TemplateSet {
    std::size_t dim = 0;
    int folds = 0;
    bool real_faces = false;
    std::string source;
    std::string description;
    std::vector<Pair> pairs;

    std::size_t size() const { return pairs.size(); }
    int genuine_count() const;
    int impostor_count() const;
    // Largest deviation of any template from unit L2 norm.
    double max_norm_error() const;
};

// Reads a container. Returns false with a single actionable sentence in
// `error`, never a bare stream failure.
bool load_templates(const std::string& path, TemplateSet& out, std::string& error);

} // namespace ffv

#endif // FFV_TEMPLATES_HPP
