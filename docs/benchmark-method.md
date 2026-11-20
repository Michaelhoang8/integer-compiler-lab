# Measurement protocol

## Questions

1. How many register instructions do the optimization passes remove?
2. Does that reduce execution time in this particular Python VM?
3. How does compile-plus-optimize cost compare with the per-call savings against direct tree interpretation?
4. Does optimization preserve observable arithmetic failures?

## Workloads

| Name | Construction | Expected limitation |
|---|---|---|
| constant_heavy | Thirty constant arithmetic bindings, last value used with an input | Intentionally favorable to folding and dead-code elimination |
| repeated_terms | Twenty identical terms, all included in the return sum | Exposes sharing but retains the addition chain |
| identity_chain | Thirty links containing zero/one identities | Deliberately redundant; not a realistic general workload |
| runtime_chain | Twenty-four dependent modular arithmetic steps | Dependencies retain real work; constant registers may still merge |
| preserved_trap | Unused input-dependent division before a zero-valued return | Timed with nonzero divisor; tests exercise the zero-divisor failure |

Sources are committed in `results/workloads/`; all three engines receive the same fixed integer inputs per workload. Input values and expected results are in `results/correctness.json`.

## Procedure

- Parse once, outside execution timing; lower and optimize once for execution trials.
- Check that the tree interpreter, baseline VM and optimized VM agree before timing.
- Warm each engine with 100 calls.
- Run 25 rounds. Shuffle engine order within each round using seed 41289.
- Each sample calls one engine 300 times. Record total `perf_counter_ns` elapsed time and divide by call count.
- Disable Python cyclic garbage collection only during execution timing, restoring its prior state afterward.
- Include Python function dispatch, input validation, register allocation and a checksum XOR inside the timed loop. Do not subtract estimated harness overhead.
- Separately measure 25 compile-plus-optimize samples, each averaging 20 operations on an already parsed AST.

`--quick` uses five rounds and 40 execution calls per sample, for CI only. Sources and correctness behavior stay the same.

## Outputs and interpretations

`raw_timings.csv` preserves every execution sample. Rows are in execution order. `summary.csv` includes minimum, maximum, median and a p95 of **sample means**; it is not an individual-call tail-latency measurement. `compile_timings.csv` retains compiler costs. `optimizer_counts.csv` records pass events. `metadata.json` captures Python/OS/architecture, timer details, protocol and the core source hash without publishing hostname or user paths.

The instruction chart counts all instructions executed on a successful call, including constants and inputs. Register indexes are not compacted; this can affect allocation cost and is included in timings.

The amortization estimate is `ceil(median_compile_cost / (median_tree_call - median_optimized_call))`, when the denominator is positive. It excludes parsing on both sides. It combines separate medians and assumes identical repeated inputs; it is an illustrative model, not a measured end-to-end crossover. A nonpositive denominator produces no estimated crossover.

## Limits

These are warmed, single-process, Python microbenchmarks. CPU scheduling, frequency changes and other system activity are uncontrolled. There is no CPU affinity, isolated host, cache-flush protocol, hardware-counter collection or statistical significance claim. Workloads are synthetic and intentionally expose specific transformations. The optimized VM can be slower on other inputs or runtimes. No native-machine-code comparison is presented.

Run `python scripts/run_experiments.py --output-dir build/my-run` to collect a separate environment's results without replacing the published run. CI verifies correctness and executable experiment generation, not a minimum speedup.
