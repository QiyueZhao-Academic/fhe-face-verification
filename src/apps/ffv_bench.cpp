// SPDX-License-Identifier: MIT
//
// Entry point for the benchmark. All logic lives in src/bench.

#include "../bench/bench.hpp"

int main(int argc, char** argv) { return ffv::bench::run(argc, argv); }
