cmake_minimum_required(VERSION 3.16)
project(ckks_dot LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# Homebrew (Apple Silicon) installs SEAL and nlohmann_json under /opt/homebrew.
# scripts/build_cpp.sh passes CMAKE_PREFIX_PATH=$(brew --prefix) explicitly.
find_package(SEAL REQUIRED)
find_package(nlohmann_json 3.2 REQUIRED)

message(STATUS "Found Microsoft SEAL ${SEAL_VERSION}")

add_executable(ckks_dot ckks_dot.cpp)
target_link_libraries(ckks_dot PRIVATE SEAL::seal nlohmann_json::nlohmann_json)
