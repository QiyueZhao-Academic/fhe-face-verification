// SPDX-License-Identifier: MIT
//
// Small filesystem helpers and the plain-text session descriptor that lets the
// client and the server agree on parameters without sharing code state.

#ifndef FFV_IO_HPP
#define FFV_IO_HPP

#include <cstdint>
#include <string>

#include "ffv/crypto.hpp"

namespace ffv {

bool make_dirs(const std::string& path, std::string& error);
bool file_exists(const std::string& path);
std::int64_t file_size(const std::string& path);
std::string join(const std::string& a, const std::string& b);

// Writes / reads a two-column "key value" descriptor. Keeping the parameters in
// a readable file means a run can be reproduced from the session directory
// alone, with no command line archaeology.
bool write_session(const std::string& path, const Params& p, Fold f, std::string& error);
bool read_session(const std::string& path, Params& p, Fold& f, std::string& error);

// Saves any SEAL object that exposes save(std::ostream&).
template <typename T>
bool save_object(const T& object, const std::string& path, std::string& error);

} // namespace ffv

#endif // FFV_IO_HPP
