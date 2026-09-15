#ifndef EXECUTOR_ALGORITHMS_H
#define EXECUTOR_ALGORITHMS_H

#include "types.h"
#include "engine.h"
#include <vector>
#include <memory>
#include <string>
#include <cmath>

/**
 * ExecutionAlgorithm
 * 
 * Base class for execution algorithms.
 * An algorithm takes a parent order and generates child orders to execute it.
 * 
 * Example: TWAP splits 1000 shares into 10 orders of 100 shares each.
 */
class ExecutionAlgorithm {
public:
    virtual ~ExecutionAlgorithm() = default;
    
    /**
     * Generate child orders for execution
     * 
     * Args:
     *   parent_order_id: ID of the parent order
     *   side: Buy or Sell
     *   total_qty: Total quantity to execute
     *   limit_price: Price limit (0 for market)
     *   num_slices: Number of child orders to create
     * 
     * Returns:
     *   Vector of Order objects ready to submit
     */
    virtual std::vector<Order> generate_orders(
        uint64_t parent_order_id,
        OrderSide side,
        uint64_t total_qty,
        double limit_price,
        int num_slices
    ) = 0;
    
    /**
     * Get algorithm name
     */
    virtual std::string name() const = 0;
};

/**
 * TWAPAlgorithm
 * 
 * Time-Weighted Average Price
 * 
 * Strategy: Split order into equal-sized slices and submit one per time period.
 * Goal: Minimize market impact by spreading execution over time.
 * 
 * Example:
 *   Want to buy 1000 shares
 *   Split into 10 slices of 100 shares each
 *   Submit one slice per minute
 *   Avg execution price = VWAP-ish (but time-based, not volume-based)
 * 
 * Advantages:
 *   - Simple to understand and implement
 *   - Predictable execution schedule
 *   - Good baseline algorithm
 * 
 * Disadvantages:
 *   - Ignores market volume
 *   - May execute when liquidity is low
 */
class TWAPAlgorithm : public ExecutionAlgorithm {
public:
    /**
     * Generate time-weighted child orders
     * 
     * Divides total_qty equally across num_slices
     * Each order is a limit order at the specified price
     */
    std::vector<Order> generate_orders(
        uint64_t parent_order_id,
        OrderSide side,
        uint64_t total_qty,
        double limit_price,
        int num_slices
    ) override;
    
    std::string name() const override { return "TWAP"; }
};

/**
 * VWAPAlgorithm
 * 
 * Volume-Weighted Average Price
 * 
 * Strategy: Execute in proportion to expected market volume.
 * Executes more when volume is high, less when volume is low.
 * Goal: Better execution prices by following natural volume patterns.
 * 
 * Example:
 *   Expected volume profile: [0.3, 0.2, 0.2, 0.15, 0.15]
 *   Total order: 1000 shares
 *   Slice 1: 300 shares (30% of volume)
 *   Slice 2: 200 shares (20% of volume)
 *   etc.
 * 
 * Advantages:
 *   - Better prices (follows natural volume)
 *   - Lower market impact
 *   - Professional algorithm (widely used)
 * 
 * Disadvantages:
 *   - Requires volume forecast
 *   - More complex to implement
 *   - Sensitive to volume forecast accuracy
 */
class VWAPAlgorithm : public ExecutionAlgorithm {
private:
    std::vector<double> volume_profile;  // Expected volume at each time bucket
    
public:
    /**
     * Set the volume profile (expected volume at each time bucket)
     * 
     * Profile values should sum to 1.0 (they are fractions)
     * 
     * Example:
     *   [0.4, 0.3, 0.2, 0.1]  // More volume early, less later
     */
    void set_volume_profile(const std::vector<double>& profile) {
        volume_profile = profile;
    }
    
    /**
     * Generate volume-weighted child orders
     * 
     * If no profile set, defaults to uniform (same as TWAP)
     */
    std::vector<Order> generate_orders(
        uint64_t parent_order_id,
        OrderSide side,
        uint64_t total_qty,
        double limit_price,
        int num_slices
    ) override;
    
    std::string name() const override { return "VWAP"; }
};

/**
 * AdaptiveAlgorithm (placeholder for Phase 5+)
 * 
 * Advanced strategy that adapts execution based on:
 * - Current market conditions
 * - Real-time volume
 * - Price movement
 * - Remaining time
 * 
 * Example:
 *   If price is falling, accelerate buys
 *   If price is rising, slow down buys
 *   If volume is high, increase execution
 *   If time is running out, execute faster
 */
class AdaptiveAlgorithm : public ExecutionAlgorithm {
public:
    std::vector<Order> generate_orders(
        uint64_t parent_order_id,
        OrderSide side,
        uint64_t total_qty,
        double limit_price,
        int num_slices
    ) override;
    
    std::string name() const override { return "Adaptive"; }
};

/**
 * POVAlgorithm (Percentage of Volume) - Phase 2, spec section 29.
 *
 * Strategy: target executing a fixed fraction of *realized* market volume
 * as it happens, e.g. "trade about 10% of whatever the market trades".
 *
 * This is fundamentally different from TWAP/VWAP: TWAP needs only a clock,
 * VWAP needs only a volume *forecast* fixed in advance - both can be fully
 * scheduled as a list of child orders before a single market event is
 * replayed. POV needs to know how much volume the market ACTUALLY traded,
 * tick by tick, which is only known while replay is running.
 *
 * generate_orders() (the ExecutionAlgorithm interface every other strategy
 * implements) intentionally throws for this reason: a precomputed schedule
 * for POV would either (a) silently degrade to a TWAP-style guess, which is
 * exactly the kind of fake functionality Rule 1 (spec section 40) forbids,
 * or (b) require the caller to already know the realized volume path, which
 * defeats the purpose of a live participation strategy. Real POV execution
 * is only available through ExecutionSession::run_pov(), which calls
 * next_order_qty() once per replayed market event, using that event's
 * actual traded volume.
 *
 * next_order_qty() is a pure function (no I/O, no book access, no fills -
 * see spec section 12: strategies decide what/when/how much, the execution
 * engine is solely responsible for creating fills).
 */
class POVAlgorithm : public ExecutionAlgorithm {
public:
    /**
     * participation_rate: target fraction of each event's traded volume to
     *   attempt to capture, e.g. 0.10 for 10%.
     * min_order_qty: never submit a nonzero order smaller than this
     *   (avoids a stream of 1-share child orders on noisy low-volume ticks).
     *   A computed size below this floor is submitted as 0 (skip this
     *   event) rather than rounded up, so the realized participation rate
     *   is never inflated above the target.
     * max_order_qty: cap a single child order's size (0 = unbounded).
     */
    explicit POVAlgorithm(double participation_rate = 0.1,
                           uint64_t min_order_qty = 1,
                           uint64_t max_order_qty = 0)
        : participation_rate_(participation_rate),
          min_order_qty_(min_order_qty),
          max_order_qty_(max_order_qty) {}

    std::vector<Order> generate_orders(
        uint64_t parent_order_id,
        OrderSide side,
        uint64_t total_qty,
        double limit_price,
        int num_slices
    ) override;

    /**
     * Decide how large the next child order should be, given how much
     * volume the market just traded this event and how much of the parent
     * order is still unfilled.
     *
     * qty = round(participation_rate * event_market_volume), then:
     *   - clamped to remaining_qty (never overshoot the parent order)
     *   - clamped to max_order_qty_ if set
     *   - snapped to 0 if it would be below min_order_qty_ (see above)
     *
     * Returns 0 if the market traded no volume this event: POV never
     * trades ahead of realized volume.
     */
    uint64_t next_order_qty(uint64_t event_market_volume, uint64_t remaining_qty) const;

    double participation_rate() const { return participation_rate_; }
    uint64_t min_order_qty() const { return min_order_qty_; }
    uint64_t max_order_qty() const { return max_order_qty_; }

    std::string name() const override { return "POV"; }

private:
    double participation_rate_;
    uint64_t min_order_qty_;
    uint64_t max_order_qty_;
};

#endif