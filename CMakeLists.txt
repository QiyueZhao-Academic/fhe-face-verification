# SPDX-License-Identifier: MIT
cmake_minimum_required(VERSION 3.22)
project(fhe_face_verification VERSION 2.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

# ---------------------------------------------------------------------------
# Reproducibility across hosts.
#
# The cleartext reference scores are IEEE-754 double arithmetic. Fused
# multiply-add would evaluate a*b+c at higher intermediate precision on Apple
# Silicon and at lower precision on hosts without the instruction, so the two
# platforms would disagree in the last bits and the "cleartext reference"
# column would depend on the machine. Contraction is therefore switched off.
# ---------------------------------------------------------------------------
include(CheckCXXCompilerFlag)
check_cxx_compiler_flag("-ffp-contract=off" FFV_HAS_FP_CONTRACT_OFF)
if(FFV_HAS_FP_CONTRACT_OFF)
  add_compile_options(-ffp-contract=off)
endif()

add_compile_options(-Wall -Wextra)

# SEAL's package version file requires an exact minor match, so the version is
# requested loosely here and checked below. That keeps the project buildable
# against whichever 4.x Homebrew or a source build provides.
find_package(SEAL REQUIRED)
find_package(Threads REQUIRED)

if(SEAL_VERSION VERSION_LESS "4.0.0")
  message(FATAL_ERROR
    "Microsoft SEAL ${SEAL_VERSION} was found and this project needs 4.0 or newer. "
    "Install it with `brew install seal`, or point CMAKE_PREFIX_PATH at a 4.x build.")
endif()

# SEAL exports SEAL::seal when it was built as a static library and
# SEAL::seal_shared when it was built as a shared one. Homebrew ships the shared
# build, a source build defaults to static, and both are supported here, so the
# target is discovered instead of assumed.
if(TARGET SEAL::seal)
  set(FFV_SEAL_TARGET SEAL::seal)
elseif(TARGET SEAL::seal_shared)
  set(FFV_SEAL_TARGET SEAL::seal_shared)
else()
  message(FATAL_ERROR
    "Microsoft SEAL ${SEAL_VERSION} was found, and it exports neither SEAL::seal nor "
    "SEAL::seal_shared. Reinstall it with `brew install seal`, or point CMAKE_PREFIX_PATH "
    "at a 4.x installation.")
endif()

get_target_property(FFV_SEAL_TYPE ${FFV_SEAL_TARGET} TYPE)
message(STATUS "Microsoft SEAL ${SEAL_VERSION} as ${FFV_SEAL_TARGET} (${FFV_SEAL_TYPE})")

set(FFV_EFFECTIVE_CXX_FLAGS "${CMAKE_CXX_FLAGS} ${CMAKE_CXX_FLAGS_${CMAKE_BUILD_TYPE}}")
string(STRIP "${FFV_EFFECTIVE_CXX_FLAGS}" FFV_EFFECTIVE_CXX_FLAGS)
configure_file(cmake/build_info.hpp.in
               "${CMAKE_CURRENT_BINARY_DIR}/generated/ffv/build_info.hpp" @ONLY)

# ---------------------------------------------------------------------------
# Libraries.
#
# ffv_shared and ffv_server hold no reference to the secret key, so the server
# executable links neither decryption code nor the type that carries a secret.
# ffv_client is the only library that does, and only the client executable and
# the self-test link it.
# ---------------------------------------------------------------------------
add_library(ffv_shared STATIC
  src/core/crypto.cpp
  src/core/io.cpp
  src/core/metrics.cpp
  src/core/platform.cpp
  src/core/templates.cpp)
target_include_directories(ffv_shared PUBLIC
  "${CMAKE_CURRENT_SOURCE_DIR}/include"
  "${CMAKE_CURRENT_BINARY_DIR}/generated")
target_link_libraries(ffv_shared PUBLIC ${FFV_SEAL_TARGET} Threads::Threads)

add_library(ffv_server STATIC src/core/server.cpp)
target_link_libraries(ffv_server PUBLIC ffv_shared)

add_library(ffv_client STATIC src/core/client.cpp)
target_link_libraries(ffv_client PUBLIC ffv_shared)

add_library(ffv_bench_lib STATIC
  src/bench/main.cpp
  src/bench/exp_scores.cpp
  src/bench/exp_cost.cpp
  src/bench/exp_batching.cpp
  src/bench/exp_scale.cpp
  src/bench/emit_json.cpp)
target_include_directories(ffv_bench_lib PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/src/bench")
target_link_libraries(ffv_bench_lib PUBLIC ffv_client ffv_server)

# ---------------------------------------------------------------------------
# Executables.
# ---------------------------------------------------------------------------
add_executable(ffv_bench src/apps/ffv_bench.cpp)
target_link_libraries(ffv_bench PRIVATE ffv_bench_lib)

add_executable(ffv_selftest src/apps/ffv_selftest.cpp)
target_link_libraries(ffv_selftest PRIVATE ffv_client ffv_server)

add_executable(ffv_client_app src/apps/ffv_client.cpp)
set_target_properties(ffv_client_app PROPERTIES OUTPUT_NAME ffv_client)
target_link_libraries(ffv_client_app PRIVATE ffv_client)

# The link line names ffv_server and never ffv_client.
add_executable(ffv_server_app src/apps/ffv_server.cpp)
set_target_properties(ffv_server_app PROPERTIES OUTPUT_NAME ffv_server)
target_link_libraries(ffv_server_app PRIVATE ffv_server)

enable_testing()
add_test(NAME selftest COMMAND ffv_selftest --tmp "${CMAKE_CURRENT_BINARY_DIR}/selftest")
