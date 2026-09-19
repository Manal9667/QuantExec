# CMakeLists.txt - Build configuration for Execution Optimizer
# Phase 1 (core engine) + Phase 2 (POV, latency, market impact) - see docs/PHASE2.md

cmake_minimum_required(VERSION 3.15)
project(executor)

# C++ standard: C++20
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# ============================================================================
# FIND PYTHON (required for bindings)
# ============================================================================

find_package(Python3 REQUIRED COMPONENTS Interpreter Development)

# ============================================================================
# FIND PYBIND11 (required for bindings)
# ============================================================================

find_package(pybind11 CONFIG REQUIRED)

# ============================================================================
# MAIN LIBRARY
# ============================================================================

# Create library with all source files
 add_library(executor_lib
     src/book.cpp
     src/engine.cpp
     src/execution.cpp
     src/market_data.cpp
     src/simulator.cpp
     src/algorithms.cpp
    src/costs.cpp
    src/impact.cpp
    src/replay.cpp
 )

# Compiler options
if(MSVC)
    target_compile_options(executor_lib PRIVATE /W4 /O2)
else()
    target_compile_options(executor_lib PRIVATE -Wall -Wextra -O2)
endif()

# Position-independent code: required so executor_lib (a static lib) can be
# linked into the pybind11 shared module on Linux/macOS. No-op on MSVC.
set_target_properties(executor_lib PROPERTIES POSITION_INDEPENDENT_CODE ON)

# Include directories
target_include_directories(executor_lib PUBLIC include)

# ============================================================================
# PYTHON MODULE
# ============================================================================

# Create Python module using pybind11
pybind11_add_module(executor src/py_bindings.cpp)

# Link against our library
target_link_libraries(executor PRIVATE executor_lib)

# ============================================================================
# TESTS
# ============================================================================

enable_testing()

# Test: Order Book
add_executable(test_book tests/test_book.cpp)
target_link_libraries(test_book executor_lib)
add_test(NAME test_book COMMAND test_book)

# Test: Matching Engine
add_executable(test_engine tests/test_engine.cpp)
target_link_libraries(test_engine executor_lib)
add_test(NAME test_engine COMMAND test_engine)

# Test: Market Simulator
add_executable(test_simulator tests/test_simulator.cpp)
target_link_libraries(test_simulator executor_lib)
add_test(NAME test_simulator COMMAND test_simulator)

# Test: Algorithms
add_executable(test_algorithms tests/test_algorithms.cpp)
target_link_libraries(test_algorithms executor_lib)
add_test(NAME test_algorithms COMMAND test_algorithms)

# Test: Integration (Phase 6)
add_executable(test_integrate tests/test_integrate.cpp)
target_link_libraries(test_integrate executor_lib)
add_test(NAME test_integrate COMMAND test_integrate)

add_executable(test_phase tests/test_phase.cpp)
target_link_libraries(test_phase executor_lib)
add_test(NAME test_phase COMMAND test_phase)

# Test: Transaction Cost Model
add_executable(test_costs tests/test_costs.cpp)
target_link_libraries(test_costs executor_lib)
add_test(NAME test_costs COMMAND test_costs)

add_executable(test_phase2 tests/test_phase2.cpp)
target_link_libraries(test_phase2 executor_lib)
add_test(NAME test_phase2 COMMAND test_phase2)

# Step 3: formal event/replay pipeline
add_executable(test_replay tests/test_replay.cpp)
target_link_libraries(test_replay executor_lib)
add_test(NAME test_replay COMMAND test_replay WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})

# Step 4: execution realism under stressed market conditions
add_executable(test_stress tests/test_stress.cpp)
target_link_libraries(test_stress executor_lib)
add_test(NAME test_stress COMMAND test_stress WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})
# ============================================================================
# BENCHMARKS (Phase 6)
# ============================================================================

add_executable(benchmark benchmarks/benchmark.cpp)
target_link_libraries(benchmark executor_lib)

# Step 7: evidence-based benchmark protocol (separate binary; see
# docs/BENCHMARKING.md). Kept alongside the original `benchmark` above
# rather than replacing it.
add_executable(benchmark_v2 benchmarks/benchmark_v2.cpp)
target_link_libraries(benchmark_v2 executor_lib)

# Optional: Add benchmark as a test
# add_test(NAME benchmark COMMAND benchmark)

# ============================================================================
# EXAMPLES
# ============================================================================

add_executable(demo example/demo.cpp)
target_link_libraries(demo executor_lib)

# ============================================================================
# SUMMARY
# ============================================================================

message(STATUS "")
message(STATUS "====================================================")
message(STATUS "  Execution Optimizer - Build Configuration")
message(STATUS "====================================================")
message(STATUS "C++ Standard: C++${CMAKE_CXX_STANDARD}")
message(STATUS "Python: ${Python3_VERSION}")
message(STATUS "pybind11: ${pybind11_VERSION}")
message(STATUS "")
message(STATUS "Targets:")
message(STATUS "  executor_lib    - C++ core library")
message(STATUS "  executor        - Python module")
message(STATUS "  test_*          - Unit tests (10 suites; run ctest to list them)")
message(STATUS "  benchmark       - Performance benchmarks")
message(STATUS "  demo            - Example usage")
message(STATUS "")
message(STATUS "Build with:")
message(STATUS "  cmake --build . --config Release")
message(STATUS "")
message(STATUS "Run tests:")
message(STATUS "  ctest --output-on-failure")
message(STATUS "")
message(STATUS "Run benchmarks:")
message(STATUS "  ./Release/benchmark")
message(STATUS "")
message(STATUS "====================================================")