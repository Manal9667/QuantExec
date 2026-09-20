#pragma once
// Shared GoogleTest-backed assertion helpers (spec section 32).
//
// The suites in this directory were originally written with hand-rolled
// assert_eq/assert_true/assert_near helpers, a manual pass/fail counter, and
// their own int main(). This header preserves those helper *names* - so the
// individual test bodies did not have to change - but routes every check
// through GoogleTest's EXPECT_* macros. Each former `void test_xxx()` is now a
// GoogleTest TEST() case, so the suites run under, and report through,
// GoogleTest and integrate with ctest's GoogleTest discovery.
#include <gtest/gtest.h>

#include <cmath>
#include <string>

// Generic equality check. The name is attached via SCOPED_TRACE so a failure
// still reports the human-readable label the original tests used.
template <typename A, typename E>
inline void assert_eq(const std::string& name, const A& actual, const E& expected) {
    SCOPED_TRACE(name);
    EXPECT_EQ(actual, expected);
}

// Tolerance-aware overload (matches the assert_eq(..., tolerance) helper that
// test_integrate.cpp used). Tolerance is relative to |expected|, as in the
// original implementation; tolerance <= 0 means exact double comparison.
inline void assert_eq(const std::string& name, double actual, double expected,
                      double tolerance) {
    SCOPED_TRACE(name);
    if (tolerance <= 0.0) {
        EXPECT_DOUBLE_EQ(actual, expected);
    } else {
        EXPECT_NEAR(actual, expected, std::abs(expected * tolerance));
    }
}

inline void assert_true(const std::string& name, bool condition) {
    SCOPED_TRACE(name);
    EXPECT_TRUE(condition);
}

// Absolute-tolerance floating point check (matches test_simulator.cpp's
// assert_near, default tolerance 1e-9).
inline void assert_near(const std::string& name, double actual, double expected,
                        double tolerance = 1e-9) {
    SCOPED_TRACE(name);
    EXPECT_NEAR(actual, expected, tolerance);
}

inline bool close_enough(double a, double b, double eps = 1e-9) {
    return std::fabs(a - b) < eps;
}
