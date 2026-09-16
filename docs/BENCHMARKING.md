# Benchmarking Methodology (Step 7)

This document is what makes any performance number in this project a
**claim you can check**, not a claim you have to take on faith. Every
number below was produced by the commands shown, on the machine described
in §1, and can be reproduced by running those same commands.

## 1. Reference machine (this baseline)

| Item | Value |
|---|---|
| OS | Ubuntu 24.04.4 LTS (x86_64) |
| CPU | Intel(R) Xeon(R) Processor @ 2.10GHz (1 vCPU available in this environment) |
| Compiler | g++ 13.3.0 |
| Build type | Release (`-DCMAKE_BUILD_TYPE=Release`, `NDEBUG` defined - `benchmark_v2` checks and prints this) |
| Python | 3.12.3 |

Numbers from a different machine are not comparable to the ones below -
re-run the protocol on your own hardware and record your own table in
the same shape rather than treating this table as universal.

## 2. Workload definition

Every run defines its workload explicitly and `benchmark_v2` prints it:

| Field | How it's set |
|---|---|
| Number of market events | Row count of the dataset passed as `argv[1]` |
| Order-book depth | Top-of-book + up to 2 additional levels, whatever the dataset's `bid_depth`/`ask_depth` columns provide |
| Number of orders | Fixed per stage (see §3) so stages are comparable across dataset sizes |
| Strategy | TWAP, 5 slices, for `full_execution` and `strategy_logic` stages |
| Number of fills | Whatever `ExecutionSession::run()` actually produces for that dataset - not fixed, since it depends on displayed liquidity |
| Dataset content fingerprint | FNV-1a of the file's bytes, printed by `benchmark_v2` for quick same-file confirmation between two runs. This is **not** the authoritative checksum - that's the SHA-256 from `scripts/build_dataset_manifest.py` (see `dataset.md`). `benchmark_v2` avoids re-implementing SHA-256 just for a benchmark sanity check. |

## 3. How to run it

```bash
# Build (Release - the binary itself warns if NDEBUG isn't set)
mkdir -p build && cd build
cmake -DCMAKE_BUILD_TYPE=Release -Dpybind11_DIR="$(python3 -c 'import pybind11; print(pybind11.get_cmake_dir())')" ..
cmake --build . --config Release -j"$(nproc)"
cd ..

# C++ stages: parsing, replay, matching, strategy logic, full execution, analytics
./build/benchmark_v2 datasets/sample_synthetic.csv
./build/benchmark_v2 /tmp/bench_10k.csv        # or any larger generated dataset - see below

# Python boundary specifically (separate script - see §4)
PYTHONPATH=build python3 python/benchmark_python_boundary.py datasets/sample_synthetic.csv

# Generate a larger synthetic workload for scaling comparisons
python3 -c "
import sys; sys.path.insert(0, 'datasets')
from generate_sample import generate
generate('/tmp/bench_10k.csv', num_rows=10000, seed=42)
"
```

Every stage in `benchmark_v2` runs **3 warm-up iterations (discarded)**
then **10 measured iterations**, reporting median, p95, mean, min, and
max - never a single sample. Warm-up exists because the first call into a
freshly-loaded code path pays one-time costs (page faults, allocator
warm-up) that don't represent steady-state behavior; reporting only mean
or only one run would hide the variance that actually matters when
deciding whether a regression is real.

## 4. Why the Python boundary is measured separately

`benchmark_v2` measures every stage in pure C++, where there is no
Python/pybind11 boundary to cross. That number alone cannot tell you what
calling the engine *from Python* (as the FastAPI backend and every
`python/*.py` script do) actually costs on top of the pure-C++ number.
`python/benchmark_python_boundary.py` runs the identical
`ExecutionSession.run()` call from Python and reports its own
median/p95; the difference between its median and `benchmark_v2`'s
`full_execution (TWAP)` median for the *same dataset* is the pybind11
crossing cost specifically (argument marshalling + GIL + Python object
construction for the returned result), not a measurement of "how fast is
Python" in general.

## 5. Recorded baseline (this machine, this repository state)

### 5.1 `datasets/sample_synthetic.csv` (15 events)

```
parsing (CSV load)     median=0.0207 ms   p95=0.0207 ms
replay (iterate)       median=0.0208 ms   p95=0.0210 ms
matching               median=0.0241 ms   p95=0.0254 ms
strategy_logic (TWAP)  median=0.0004 ms   p95=0.0004 ms
full_execution (TWAP)  median=0.0227 ms   p95=0.0270 ms
analytics (costs)      median=0.0000 ms   p95=0.0001 ms
Peak RSS: 3884 KB
```

Python boundary, same dataset: median **0.0322 ms** (vs. 0.0227 ms pure
C++) → **≈0.0095 ms** pybind11 crossing overhead per `run()` call on this
tiny dataset (dominated by fixed marshalling cost, not data volume).

### 5.2 10,000-event synthetic workload (`generate_sample.generate(num_rows=10000, seed=42)`)

```
parsing (CSV load)     median=17.6674 ms   p95=18.0470 ms
replay (iterate)       median=17.9230 ms   p95=18.2362 ms
matching               median=19.3744 ms   p95=19.4997 ms
strategy_logic (TWAP)  median=0.0004 ms    p95=0.0005 ms
full_execution (TWAP)  median=20.5730 ms   p95=20.8563 ms
analytics (costs)      median=0.0000 ms    p95=0.0001 ms
Peak RSS: 9312 KB
```

Python boundary, same dataset: median **21.4599 ms** (vs. 20.5730 ms pure
C++) → **≈0.89 ms** overhead. The overhead grew from ~0.01 ms to ~0.89 ms
between the two dataset sizes - consistent with `ExecutionResult`
carrying a `fills` list whose pybind11 marshalling cost scales with the
number of fills, not just a fixed per-call cost. This is a real,
measured shape, not a hypothesis: re-run at other sizes to check whether
it stays roughly linear before relying on it for capacity planning.

**Reading these two tables together:** parsing, replay, and matching all
scale roughly linearly with event count (≈1.8 µs/event on this machine at
10k events, vs. sub-microsecond-per-event overhead visible only at
15 events due to fixed costs dominating). `strategy_logic` and
`analytics` are independent of dataset size by construction (they operate
on the parent order and the already-computed result respectively, not on
the event stream), which is exactly why they stay flat across both
tables above - that flatness is itself a check that those two stages
don't have a hidden dependency on replay length.

## 6. Memory measurement

`benchmark_v2` reports `getrusage(RUSAGE_SELF, ...).ru_maxrss` once, at
the end of the whole run. Two honest limitations, stated rather than
hidden:

1. **This is a peak for the whole process across every stage**, not a
   per-stage measurement - `ru_maxrss` only ever grows, so it cannot tell
   you which stage caused a particular increase. Isolating per-stage
   memory would require a proper allocator hook or a tool like
   `valgrind --tool=massif`, which is out of scope for this lightweight,
   dependency-free harness.
2. It measures **resident set size**, not allocations-and-frees churn -
   a stage that allocates and frees heavily without growing peak RSS
   would look "free" here even though it's doing real allocator work.

## 7. Performance regression thresholds

`benchmark_v2` deliberately does **not** hardcode a pass/fail threshold.
A threshold measured on one machine (this repository's sandbox: 1 vCPU,
shared/virtualized) would be silently wrong - either constantly failing
or falsely reassuring - on any other machine, which is worse than no
threshold at all.

To set real thresholds for your own CI/dev machine:

1. Run `./build/benchmark_v2 datasets/sample_synthetic.csv` (and/or a
   larger generated workload) at least 3 separate times on that machine.
2. Record the median of medians per stage in a table shaped like §5
   above, in this file, under a new "§7.1 <your machine's name>" heading.
3. Pick a tolerance (e.g., "fail if median exceeds 1.5x the recorded
   baseline for that stage") appropriate to how noisy that specific
   machine's numbers are - a shared CI runner needs a looser tolerance
   than a dedicated bare-metal box.
4. Wire that comparison into whatever CI step runs `benchmark_v2`, if
   any exists yet (none does in this repository today - see
   `LIMITATIONS.md`).

## 8. What this benchmark does NOT claim

- It does not claim these numbers represent real historical-data
  workloads (no verified historical dataset exists yet - see
  `dataset.md`).
- It does not claim `matching`'s per-event cost would hold at real
  L2/L3 order-book depths - the stress datasets in `datasets/stress/`
  exercise correctness at depth edge cases, not throughput at scale.
- It does not claim any number here is representative of a production
  deployment - this is a research/backtesting engine (see `README.md`),
  and no part of this benchmark models network, disk, or database I/O
  the way a live system would incur them.
