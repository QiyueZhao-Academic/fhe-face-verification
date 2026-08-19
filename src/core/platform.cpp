// SPDX-License-Identifier: MIT

#include "ffv/platform.hpp"

#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>

#include "ffv/build_info.hpp"
#include "ffv/crypto.hpp"

#if defined(__APPLE__)
#include <sys/sysctl.h>
#include <sys/types.h>
#elif defined(__linux__)
#include <unistd.h>
#endif

namespace ffv {

namespace {

std::string trim(const std::string& s)
{
    const std::size_t a = s.find_first_not_of(" \t\r\n");
    if (a == std::string::npos) return "";
    const std::size_t b = s.find_last_not_of(" \t\r\n");
    return s.substr(a, b - a + 1);
}

#if defined(__APPLE__)
std::string sysctl_string(const char* name)
{
    std::size_t len = 0;
    if (::sysctlbyname(name, nullptr, &len, nullptr, 0) != 0 || len == 0) return "";
    std::string buf(len, '\0');
    if (::sysctlbyname(name, &buf[0], &len, nullptr, 0) != 0) return "";
    while (!buf.empty() && buf[buf.size() - 1] == '\0') buf.erase(buf.size() - 1);
    return buf;
}

long long sysctl_int(const char* name, long long fallback)
{
    long long v = 0;
    std::size_t len = sizeof(v);
    if (::sysctlbyname(name, &v, &len, nullptr, 0) == 0) return v;
    int v32 = 0;
    len = sizeof(v32);
    if (::sysctlbyname(name, &v32, &len, nullptr, 0) == 0) return v32;
    return fallback;
}

// Reads the product version from the OS property list, which is the only place
// a userspace process can see the marketing version string.
std::string macos_version()
{
    std::ifstream in("/System/Library/CoreServices/SystemVersion.plist");
    if (!in) return "";
    std::string line, prev;
    while (std::getline(in, line)) {
        if (prev.find("ProductVersion") != std::string::npos) {
            const std::size_t a = line.find("<string>");
            const std::size_t b = line.find("</string>");
            if (a != std::string::npos && b != std::string::npos && b > a) {
                return trim(line.substr(a + 8, b - a - 8));
            }
        }
        prev = line;
    }
    return "";
}
#endif

#if defined(__linux__)
std::string linux_cpu_name()
{
    std::ifstream in("/proc/cpuinfo");
    std::string line;
    while (std::getline(in, line)) {
        const std::size_t c = line.find(':');
        if (c == std::string::npos) continue;
        const std::string key = trim(line.substr(0, c));
        if (key == "model name" || key == "Model" || key == "Hardware") {
            return trim(line.substr(c + 1));
        }
    }
    return "";
}

std::string linux_release()
{
    std::ifstream in("/etc/os-release");
    std::string line;
    while (std::getline(in, line)) {
        if (line.compare(0, 12, "PRETTY_NAME=") == 0) {
            std::string v = line.substr(12);
            if (!v.empty() && v[0] == '"') v = v.substr(1, v.size() - 2);
            return v;
        }
    }
    return "";
}
#endif

} // namespace

Platform describe_platform()
{
    Platform p;
    p.compiler = FFV_COMPILER;
    p.build_type = FFV_BUILD_TYPE;
    p.cxx_flags = FFV_CXX_FLAGS;
    p.seal_version = seal_version();
    p.compression = compression_name();
    const unsigned x = 1;
    unsigned char probe[sizeof(unsigned)];
    std::memcpy(probe, &x, sizeof(unsigned));
    p.little_endian = probe[0] == 1;

#if defined(__aarch64__) || defined(_M_ARM64)
    p.arch = "arm64";
#elif defined(__x86_64__) || defined(_M_X64)
    p.arch = "x86_64";
#else
    p.arch = "unknown";
#endif

#if defined(__APPLE__)
    p.os = "macOS";
    p.os_version = macos_version();
    p.cpu = sysctl_string("machdep.cpu.brand_string");
    if (p.cpu.empty()) p.cpu = sysctl_string("hw.model");
    p.physical_cores = static_cast<int>(sysctl_int("hw.physicalcpu", 0));
    p.logical_cores = static_cast<int>(sysctl_int("hw.logicalcpu", 0));
    p.memory_bytes = sysctl_int("hw.memsize", 0);
    // A non-zero proc_translated means this process runs as x86_64 under
    // Rosetta 2, and every timing below is then an emulation figure.
    p.translated = sysctl_int("sysctl.proc_translated", 0) != 0;
#elif defined(__linux__)
    p.os = "Linux";
    p.os_version = linux_release();
    p.cpu = linux_cpu_name();
    p.logical_cores = static_cast<int>(::sysconf(_SC_NPROCESSORS_ONLN));
    p.physical_cores = p.logical_cores;
    const long pages = ::sysconf(_SC_PHYS_PAGES);
    const long page = ::sysconf(_SC_PAGE_SIZE);
    if (pages > 0 && page > 0) p.memory_bytes = static_cast<long long>(pages) * page;
#else
    p.os = "unknown";
#endif
    if (p.cpu.empty()) p.cpu = "unreported";
    return p;
}

std::string timing_caveat(const Platform& p)
{
    if (p.translated) {
        return "This process runs under Rosetta 2 translation, so every latency below "
               "describes emulated x86_64 execution and must be re-measured on a native "
               "arm64 build before it is quoted.";
    }
    if (p.build_type != "Release") {
        return "This build uses the " + p.build_type
               + " configuration, so the latencies below carry debug overhead. Configure with "
                 "CMAKE_BUILD_TYPE=Release before quoting them.";
    }
    return "This build is a native " + p.arch + " Release build, so the latencies below "
           "describe the host directly.";
}

} // namespace ffv
