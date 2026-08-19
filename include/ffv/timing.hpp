// SPDX-License-Identifier: MIT

#ifndef FFV_TIMING_HPP
#define FFV_TIMING_HPP

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <vector>

namespace ffv {

class Timer {
public:
    Timer() : t0_(std::chrono::steady_clock::now()) {}
    void reset() { t0_ = std::chrono::steady_clock::now(); }
    double ms() const
    {
        const auto d = std::chrono::steady_clock::now() - t0_;
        return std::chrono::duration<double, std::milli>(d).count();
    }

private:
    std::chrono::steady_clock::time_point t0_;
};

// Summary of repeated timings. The median is the headline number because a
// single sample on a laptop is dominated by scheduling noise.
struct Stat {
    int n = 0;
    double mean = 0.0;
    double median = 0.0;
    double stddev = 0.0;
    double min = 0.0;
    double max = 0.0;
};

inline Stat summarise(std::vector<double> xs)
{
    Stat s;
    if (xs.empty()) return s;
    std::sort(xs.begin(), xs.end());
    s.n = static_cast<int>(xs.size());
    s.min = xs.front();
    s.max = xs.back();
    double sum = 0.0;
    for (double x : xs) sum += x;
    s.mean = sum / static_cast<double>(s.n);
    const std::size_t h = xs.size() / 2;
    s.median = (xs.size() % 2 == 1) ? xs[h] : 0.5 * (xs[h - 1] + xs[h]);
    if (s.n > 1) {
        double acc = 0.0;
        for (double x : xs) acc += (x - s.mean) * (x - s.mean);
        s.stddev = std::sqrt(acc / static_cast<double>(s.n - 1));
    }
    return s;
}

} // namespace ffv

#endif // FFV_TIMING_HPP
