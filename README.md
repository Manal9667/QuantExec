# Algorithmic Trade Execution Engine

> A C++ execution engine for optimizing large-order execution using market microstructure, quantitative strategies, and machine learning.

## Overview

Executing a large order is not simply a matter of buying or selling the entire quantity at once. Large orders can consume liquidity, increase market impact, and result in unfavorable execution prices.

This project investigates:

> **Can adaptive execution strategies reduce the cost of executing large orders compared with traditional approaches?**

The system combines a **C++20 matching engine**, algorithmic execution strategies, real-time and historical market data, machine learning, and execution analytics.

## Architecture

```text
                         Parent Order
                              |
                              v
                    Execution Algorithm
                              |
                 +------------+------------+
                 |            |            |
                TWAP         VWAP       ML-VWAP
                 |            |            |
                 +------------+------------+
                              |
                              v
                       Market Data
                              |
                 +------------+------------+
                 |                         |
            Synthetic                    Real
             Market                    Market
                 |                         |
                 +------------+------------+
                              |
                              v
                       Matching Engine
                              |
                              v
                     Execution Results
                              |
                              v
                       Cost Analytics
```

The execution engine is separated from the market environment so that the same strategies can be evaluated against **synthetic, real-time, and historical market conditions**.

## Core Components

### C++ Matching Engine

The execution engine implements:

* **Price-time priority**
* **Multi-level order matching**
* **Limit and market orders**
* **Partial fills**
* **Best bid and ask tracking**
* **Liquidity consumption**
* **Order-book updates**

The matching engine executes orders according to market rules, while higher-level execution algorithms determine how a large parent order should be divided and scheduled.

### Execution Algorithms

#### TWAP

**Time-Weighted Average Price** distributes an order relatively evenly over a specified execution period.

#### VWAP

**Volume-Weighted Average Price** distributes execution according to an expected market-volume profile.

#### ML-VWAP

**ML-VWAP** uses predicted short-term trading volume to dynamically adjust the execution schedule.

The objective is to determine whether machine-learning-based volume forecasts can improve execution relative to traditional VWAP.

## Machine Learning

### Random Forest Volume Forecasting

A **Random Forest regression model** forecasts short-term trading volume using historical market information.

```text
Historical Market Data
        |
        v
Feature Engineering
        |
        v
Random Forest Regressor
        |
        v
Predicted Trading Volume
        |
        v
      ML-VWAP
        |
        v
   Child Orders
```

The model predicts **trading activity rather than stock prices**.

## Market Data

The system supports multiple market environments.

### Synthetic Market

Used for:

* Unit and integration testing
* Controlled market scenarios
* Order-book edge cases
* Reproducible experiments

### Real Market

Real-time market information is used to evaluate execution strategies under actual market conditions.

Where available, the system captures:

* Timestamp
* Bid / Ask
* Bid Size / Ask Size
* Last Trade
* Trade Size
* Volume

### Historical Market

Historical market data is replayed chronologically to evaluate strategies without lookahead bias.

The system explicitly documents which fields are available for each dataset rather than assuming that historical data contains full order-book depth.

## Backtesting

Historical backtests use chronological **training, validation, and test periods**.

```text
Past -------------------------------------------------> Future

|--------- Training ---------|--- Validation ---|--- Test ---|
```

Future market information is never made available to the model or execution algorithm before it would have existed in the market.

This allows **TWAP, VWAP, and ML-VWAP** to be compared under identical market conditions.

## Execution Analytics

The system evaluates execution quality using:

| Metric                       | Description                                    |
| ---------------------------- | ---------------------------------------------- |
| **Average Execution Price**  | Average price paid or received                 |
| **Slippage**                 | Difference between arrival and execution price |
| **Implementation Shortfall** | Cost relative to the decision/arrival price    |
| **Fill Rate**                | Percentage of the parent order executed        |
| **Market Impact**            | Price movement associated with execution       |
| **VWAP Deviation**           | Execution performance relative to market VWAP  |
| **Completion Time**          | Time required to complete the order            |

## Research Question

The final experiment focuses on:

> **Can short-term volume forecasting improve large-order execution compared with traditional VWAP?**

TWAP, VWAP, and ML-VWAP will be evaluated using the same historical market conditions and compared across:

* Execution cost
* Slippage
* Implementation shortfall
* Fill rate
* Market impact
* Completion time

## Technology

**Core**

* C++20
* CMake
* STL

**Quantitative Research & Machine Learning**

* Python
* NumPy
* Pandas
* scikit-learn

**Market Data**

* Real-time market-data APIs
* Historical market data
* Synthetic market simulation

**Frontend**

* React
* TypeScript

**Testing**

* CTest
* C++ integration tests
* Historical backtesting

## Roadmap

* [x] C++ matching engine
* [x] Limit and market orders
* [x] Partial fills
* [x] TWAP
* [x] VWAP
* [x] Synthetic market environment
* [ ] Real-time market-data integration
* [ ] Historical market replay
* [ ] Execution analytics
* [ ] Random Forest volume forecasting
* [ ] ML-VWAP
* [ ] Strategy comparison
* [ ] React/TypeScript dashboard

## Disclaimer

This project is intended for educational and research purposes focused on algorithmic execution and market microstructure. It is not financial advice and is not intended for live trading.
