# Measured findings

Recorded 2026-11-20T22:04:33.203920+00:00 on CPython 3.13.17 / Windows AMD64.

| Workload | Baseline VM μs | Optimized VM μs | VM speedup | Compile + optimize μs | Estimated calls to amortize vs tree |
|---|---:|---:|---:|---:|---:|
| constant_heavy | 21.22 | 0.92 | 23.20× | 349.56 | 19 |
| repeated_terms | 14.86 | 4.06 | 3.66× | 199.88 | 15 |
| identity_chain | 12.92 | 0.48 | 26.97× | 151.50 | 10 |
| runtime_chain | 13.86 | 11.40 | 1.22× | 231.78 | 40 |
| preserved_trap | 0.98 | 0.81 | 1.21× | 9.38 | 215 |


Each execution number is the median of 25 sample means, each containing 300 calls. The p95 field in summary.csv is a percentile of sample means, not an individual request-latency p95. Raw elapsed nanoseconds and sample order are committed.

The largest reductions occur where the generator deliberately exposes constants, repeated terms and identity chains. The runtime chain retains its arithmetic dependencies and serves as a less optimizable comparison. These workloads do not estimate performance on general programs.

Amortization divides median compile-plus-optimization cost by the measured per-call difference between the tree interpreter and optimized VM, rounded up. Parsing is excluded on both paths. This is an illustrative estimate combining separate measurements, not a measured end-to-end deployment threshold. Baseline-VM speedup answers a different question: the effect of optimization within this VM implementation.

Decision: keep all potentially trapping division and modulo instructions live, even if their result is unused. Small extra execution cost is preferable to silently changing the language. The compiler remains an educational register interpreter, not a native-code/JIT performance claim.
