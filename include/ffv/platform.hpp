// SPDX-License-Identifier: MIT
//
// Host and build description. A timing that does not name the machine it was
// measured on cannot be reproduced, and a timing measured under Rosetta cannot
// be published at all, so both facts are recorded next to the numbers.

#ifndef FFV_PLATFORM_HPP
#define FFV_PLATFORM_HPP

#include <string>

namespace ffv {

struct Platform {
    std::string os;            // "macOS", "Linux", ...
    std::string os_version;
    std::string arch;          // "arm64", "x86_64"
    std::string cpu;           // marketing name where the OS exposes one
    int physical_cores = 0;
    int logical_cores = 0;
    long long memory_bytes = 0;
    bool translated = false;   // running under Rosetta 2
    std::string compiler;
    std::string build_type;
    std::string cxx_flags;
    std::string seal_version;
    std::string compression;
    bool little_endian = true;
};

Platform describe_platform();

// One sentence naming why a timing from this host is or is not publishable.
std::string timing_caveat(const Platform& p);

} // namespace ffv

#endif // FFV_PLATFORM_HPP
