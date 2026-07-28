#!/usr/bin/env bash
# Build the native Microsoft SEAL driver (cpp/ckks_dot.cpp).
# Tested against Homebrew: seal 4.3.x, nlohmann-json 3.12, cmake 4.x, macOS arm64.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${ROOT}/cpp/build"

# Homebrew prefix: /opt/homebrew on Apple Silicon, /usr/local on Intel.
if command -v brew >/dev/null 2>&1; then
  PREFIX="$(brew --prefix)"
else
  PREFIX="/usr/local"
  echo "warning: brew not found, falling back to ${PREFIX}" >&2
fi

echo "== configuring (CMAKE_PREFIX_PATH=${PREFIX}) =="
cmake -S "${ROOT}/cpp" -B "${BUILD_DIR}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH="${PREFIX}"

echo "== building =="
cmake --build "${BUILD_DIR}" --parallel

echo "== smoke test =="
"${BUILD_DIR}/ckks_dot" --version
echo "binary: ${BUILD_DIR}/ckks_dot"
