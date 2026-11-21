"""Measure real Python execution; export raw samples, listings, charts and report.

Run from any directory. Default output: results/ and docs/ in this repository.
--output-dir isolates CI experiments from checked-in local measurements.
"""
from pathlib import Path
import argparse
import csv
from datetime import datetime, timezone
import gc
import hashlib
import html
import json
import platform
import random
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from integer_compiler import parse, evaluate, compile_program, optimize, execute, disassemble


def workloads():
    constants = ['input x;'] + [f'let a{i} = ({i+7} * 13) + (48 // 6);' for i in range(30)]
    constants.append('return x + a29;')
    repeated = ['input x;', 'input y;'] + [f'let a{i} = (x + 7) * (y + 3);' for i in range(20)]
    repeated.append('return ' + ' + '.join(f'a{i}' for i in range(20)) + ';')
    identities = ['input x;', 'let a0 = (x + 0) * 1;']
    identities += [f'let a{i} = (a{i-1} - 0) // 1;' for i in range(1, 30)]
    identities.append('return a29;')
    runtime = ['input x;', 'input y;', 'let a0 = (x * 17 + y) % 100003;']
    runtime += [f'let a{i} = (a{i-1} * 17 + y) % 100003;' for i in range(1, 24)]
    runtime.append('return a23;')
    return {
        'constant_heavy': ('\n'.join(constants), {'x': 37}),
        'repeated_terms': ('\n'.join(repeated), {'x': 37, 'y': 11}),
        'identity_chain': ('\n'.join(identities), {'x': -37}),
        'runtime_chain': ('\n'.join(runtime), {'x': 37, 'y': 11}),
        'preserved_trap': ((ROOT/'examples/trap_preservation.int').read_text(), {'x': 37, 'divisor': 3}),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve() if args.output_dir else ROOT
    results = out/'results'
    docs = out/'docs'
    for path in [results/'listings', results/'workloads', docs/'charts']:
        path.mkdir(parents=True, exist_ok=True)
    samples, iterations = (5, 40) if args.quick else (25, 300)
    rng = random.Random(41289)
    raw = []
    summary = []
    all_counts = []
    correctness = []
    for name, (source, values) in workloads().items():
        program = parse(source)
        base = compile_program(program)
        optimization = optimize(base)
        optimized = optimization.code
        variants = {
            'tree_interpreter': lambda: evaluate(program, values),
            'baseline_vm': lambda: execute(base, values),
            'optimized_vm': lambda: execute(optimized, values),
        }
        expected = evaluate(program, values)
        for label, run in variants.items():
            assert run() == expected
            for _ in range(100):
                run()
        correctness.append({'workload': name, 'inputs': values, 'result': expected, 'engines_agree': True})
        (results/f'workloads/{name}.int').write_text(source.rstrip()+'\n', encoding='utf-8')
        (results/f'listings/{name}.baseline.ir').write_text(disassemble(base), encoding='utf-8')
        (results/f'listings/{name}.optimized.ir').write_text(disassemble(optimized), encoding='utf-8')
        # Rotate engine order per round to reduce systematic ordering bias. Wall
        # clock includes function dispatch, input validation and register allocation.
        for round_id in range(samples):
            order = list(variants)
            rng.shuffle(order)
            for label in order:
                run = variants[label]
                was_enabled = gc.isenabled()
                gc.disable()
                try:
                    started = time.perf_counter_ns()
                    checksum = 0
                    for _ in range(iterations):
                        checksum ^= run()
                    elapsed = time.perf_counter_ns() - started
                finally:
                    if was_enabled:
                        gc.enable()
                raw.append({'workload': name, 'engine': label, 'round': round_id,
                            'iterations': iterations, 'elapsed_ns': elapsed,
                            'ns_per_call': elapsed/iterations, 'checksum': checksum})
        for label in variants:
            times = [r['ns_per_call'] for r in raw if r['workload'] == name and r['engine'] == label]
            ordered = sorted(times)
            p95 = ordered[min(len(ordered)-1, int(.95*len(ordered)))]
            summary.append({'workload': name, 'engine': label, 'median_ns': statistics.median(times),
                            'p95_sample_mean_ns': p95, 'min_ns': min(times), 'max_ns': max(times),
                            'samples': samples, 'calls_per_sample': iterations,
                            'baseline_instructions': len(base.instructions),
                            'optimized_instructions': len(optimized.instructions)})
        all_counts.append({'workload': name, **dict(optimization.counts)})

    # Measure compiler cost independently from steady-state execution. This uses
    # already parsed programs, so the break-even analysis excludes parsing for both.
    compile_samples = []
    for name, (source, _) in workloads().items():
        program = parse(source)
        for round_id in range(samples):
            started = time.perf_counter_ns()
            for _ in range(20):
                optimize(compile_program(program))
            compile_samples.append({'workload': name, 'round': round_id,
                                    'compile_and_optimize_ns': (time.perf_counter_ns()-started)/20})

    def write_csv(name, rows):
        with (results/name).open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    write_csv('raw_timings.csv', raw)
    write_csv('summary.csv', summary)
    write_csv('optimizer_counts.csv', all_counts)
    write_csv('compile_timings.csv', compile_samples)
    metadata = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
                'python': sys.version.split()[0], 'implementation': platform.python_implementation(),
                'os': platform.system(), 'os_release': platform.release(), 'machine': platform.machine(),
                'timer': 'perf_counter_ns', 'timer_resolution_seconds': time.get_clock_info('perf_counter').resolution,
                'gc_during_timed_execution': False, 'samples_per_engine': samples,
                'iterations_per_sample': iterations, 'warmup_calls_per_engine': 100,
                'engine_order': 'seeded shuffle each round', 'seed': 41289,
                'source_sha256': hashlib.sha256((ROOT/'src/integer_compiler/core.py').read_bytes()).hexdigest(),
                'scope': 'Local Python microbenchmarks on synthetic straight-line integer programs; no CPU affinity, no hardware counters, not native machine code'}
    (results/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n', encoding='utf-8')
    (results/'correctness.json').write_text(json.dumps(correctness, indent=2)+'\n', encoding='utf-8')
    render(summary, all_counts, compile_samples, metadata, results, docs)
    print(json.dumps({'results': str(results), 'report': str(docs/'report.html'), 'timed_samples': len(raw)}))


def render(summary, counts, compile_samples, metadata, results, docs):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'figure.facecolor': '#f5f3ed', 'axes.facecolor': '#f5f3ed',
                         'axes.spines.top': False, 'axes.spines.right': False, 'axes.titlelocation': 'left',
                         'axes.titleweight': 'bold', 'font.size': 11, 'savefig.dpi': 160})
    names = list(dict.fromkeys(r['workload'] for r in summary))
    engines = ['tree_interpreter', 'baseline_vm', 'optimized_vm']
    colors = ['#a8abae', '#566572', '#d15d35']
    by = {(r['workload'], r['engine']): r for r in summary}
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(12, 5.3))
    for i, engine in enumerate(engines):
        ax.bar(x+(i-1)*.24, [by[n, engine]['median_ns']/1000 for n in names], .24,
               label=engine.replace('_',' '), color=colors[i])
    ax.set_yscale('log'); ax.set_ylabel('Median sample mean, Î¼s / call (log scale)')
    ax.set_xticks(x, [n.replace('_','\n') for n in names]);ax.legend(frameon=False, ncol=3)
    ax.set_title('Measured execution cost', fontsize=22, pad=22)
    fig.tight_layout();fig.savefig(docs/'charts/execution.png');plt.close(fig)
    fig, ax = plt.subplots(figsize=(12, 5.3))
    before = [by[n, 'baseline_vm']['baseline_instructions'] for n in names]
    after = [by[n, 'baseline_vm']['optimized_instructions'] for n in names]
    ax.barh(x+.18, before, .35, color=colors[1], label='Baseline IR')
    ax.barh(x-.18, after, .35, color=colors[2], label='Optimized IR')
    ax.set_yticks(x, [n.replace('_',' ') for n in names]);ax.invert_yaxis();ax.set_xlabel('Instructions executed per successful call')
    ax.legend(frameon=False);ax.set_title('Work removed; observable traps retained', fontsize=22, pad=22)
    for i, (b,a) in enumerate(zip(before,after)):
        ax.text(b+2,i+.18,str(b),va='center');ax.text(a+2,i-.18,str(a),va='center')
    fig.tight_layout();fig.savefig(docs/'charts/instructions.png');plt.close(fig)
    table = []
    for n in names:
        base = by[n,'baseline_vm'];opt = by[n,'optimized_vm'];tree = by[n,'tree_interpreter']
        compile_ns = statistics.median(r['compile_and_optimize_ns'] for r in compile_samples if r['workload']==n)
        saving = tree['median_ns']-opt['median_ns']
        breakeven = str(int(np.ceil(compile_ns/saving))) if saving > 0 else 'No measured crossover'
        table.append({'workload': n, 'baseline_us': base['median_ns']/1000, 'optimized_us': opt['median_ns']/1000,
                      'vm_speedup': base['median_ns']/opt['median_ns'], 'tree_us': tree['median_ns']/1000,
                      'compile_us': compile_ns/1000, 'estimated_calls_to_amortize_vs_tree': breakeven})
    with (results/'tradeoffs.csv').open('w', newline='', encoding='utf-8') as f:
        w=csv.DictWriter(f, fieldnames=list(table[0]));w.writeheader();w.writerows(table)
    md = '| Workload | Baseline VM Î¼s | Optimized VM Î¼s | VM speedup | Compile + optimize Î¼s | Estimated calls to amortize vs tree |\n|---|---:|---:|---:|---:|---:|\n'
    for r in table:
        md += f"| {r['workload']} | {r['baseline_us']:.2f} | {r['optimized_us']:.2f} | {r['vm_speedup']:.2f}Ã— | {r['compile_us']:.2f} | {r['estimated_calls_to_amortize_vs_tree']} |\n"
    (results/'findings.md').write_text(f'''# Measured findings

Recorded {metadata['recorded_at_utc']} on {metadata['implementation']} {metadata['python']} / {metadata['os']} {metadata['machine']}.

{md}

Each execution number is the median of {metadata['samples_per_engine']} sample means, each containing {metadata['iterations_per_sample']} calls. The p95 field in summary.csv is a percentile of sample means, not an individual request-latency p95. Raw elapsed nanoseconds and sample order are committed.

The largest reductions occur where the generator deliberately exposes constants, repeated terms and identity chains. The runtime chain retains its arithmetic dependencies and serves as a less optimizable comparison. These workloads do not estimate performance on general programs.

Amortization divides median compile-plus-optimization cost by the measured per-call difference between the tree interpreter and optimized VM, rounded up. Parsing is excluded on both paths. This is an illustrative estimate combining separate measurements, not a measured end-to-end deployment threshold. Baseline-VM speedup answers a different question: the effect of optimization within this VM implementation.

Decision: keep all potentially trapping division and modulo instructions live, even if their result is unused. Small extra execution cost is preferable to silently changing the language. The compiler remains an educational register interpreter, not a native-code/JIT performance claim.
''',encoding='utf-8')
    source=(ROOT/'examples/trap_preservation.int').read_text()
    before=(results/'listings/preserved_trap.baseline.ir').read_text()
    after=(results/'listings/preserved_trap.optimized.ir').read_text()
    rows=''.join(f"<tr><td>{r['workload'].replace('_',' ')}</td><td>{r['baseline_us']:.2f}</td><td>{r['optimized_us']:.2f}</td><td>{r['vm_speedup']:.2f}Ã—</td><td>{r['estimated_calls_to_amortize_vs_tree']}</td></tr>" for r in table)
    report=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Integer compiler Â· experiment report</title>
<style>*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:#f5f3ed;color:#20252b;font:17px/1.6 system-ui,sans-serif}}header{{background:#20252b;color:#f5f3ed;padding:38px 7vw 50px}}header .tag{{color:#ee9b77;font:13px ui-monospace,monospace;letter-spacing:2px}}h1{{font-size:66px;line-height:1.05;letter-spacing:-3px;margin:22px 0}}h2{{font-size:36px;line-height:1.2;letter-spacing:-1px;margin:0 0 25px}}h3{{font-size:19px;margin-top:0}}p{{max-width:880px}}nav{{display:flex;gap:28px;font:14px ui-monospace,monospace;margin-top:30px}}nav a{{color:inherit;text-decoration:none;border-bottom:1px solid #65717b}}main{{max-width:1320px;margin:auto;padding:0 55px}}section{{padding:58px 0;border-bottom:1px solid #d2d2ca;scroll-margin-top:15px}}.eyebrow{{color:#a64c2c;font:13px ui-monospace,monospace;letter-spacing:1px;margin-bottom:12px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:25px}}.triple{{display:grid;grid-template-columns:1.3fr 1fr 1fr;gap:20px}}.panel{{background:white;padding:24px;border:1px solid #dadbd5}}.dark{{background:#20252b;color:#f5f3ed}}pre{{font:14px/1.75 ui-monospace,Consolas,monospace;overflow:auto;margin:0}}.stat{{font-size:46px;line-height:1.2;font-weight:650;letter-spacing:-2px}}.note{{font-size:14px;color:#5e666a}}.dark .note{{color:#c6d0d5}}img{{display:block;width:100%;height:auto}}table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}td,th{{padding:16px 12px;text-align:right;border-bottom:1px solid #d2d2ca}}td:first-child,th:first-child{{text-align:left}}th{{font:12px ui-monospace,monospace;text-transform:uppercase}}code{{font-family:ui-monospace,monospace}}.rule{{border-left:4px solid #d15d35;padding:10px 25px;margin:25px 0}}footer{{padding:35px 0;color:#626a6f;font-size:13px}}@media(max-width:800px){{main{{padding:0 22px}}h1{{font-size:42px}}.grid,.triple{{grid-template-columns:1fr}}nav{{flex-wrap:wrap}}table{{font-size:12px}}}}</style>
<header id="overview"><div class="tag">LANGUAGE TOOLING / REPRODUCIBLE EXPERIMENT 01</div><h1>Integer compiler<br>optimization lab</h1><p>A parser, reference interpreter and register IR with constant folding, common-subexpression elimination and trap-preserving dead-code elimination.</p><nav><a href="#pipeline">IR and semantics</a><a href="#correctness">Correctness</a><a href="#measurements">Measurements</a><a href="#decision">Tradeoffs</a></nav></header>
<main><section id="pipeline"><div class="eyebrow">01 / THE TRANSFORMATION</div><h2>Unused does not mean removable.</h2><p>This program must still fail when <code>divisor = 0</code>. Returning a constant does not authorize dropping an eagerly evaluated division.</p><div class="triple"><div class="panel dark"><h3>Source</h3><pre>{html.escape(source)}</pre></div><div class="panel"><h3>Baseline IR</h3><pre>{html.escape(before)}</pre></div><div class="panel"><h3>Optimized IR</h3><pre>{html.escape(after)}</pre></div></div><p class="note">The division remains a liveness root. Constants and arithmetic identities may simplify the return value without suppressing an earlier error.</p></section>
<section id="correctness"><div class="eyebrow">02 / EXECUTABLE SEMANTICS</div><h2>Three engines. One resultâ€”or one error.</h2><div class="grid"><div class="panel"><h3>Language contract</h3><ul><li>Unbounded signed integers</li><li>Floor division and divisor-signed remainder</li><li>Immutable, eager let bindings</li><li>Left operand evaluated before right</li><li>All declared inputs validated up front</li></ul></div><div class="panel dark"><h3>Verification</h3><p>Run source through the independent tree interpreter, baseline IR and optimized IR. Compare values and exceptions.</p><pre>python -m unittest discover -s tests -v</pre><p class="note">Tests include negative arithmetic, missing inputs, invalid syntax, shared expressions and traps hidden inside unused or zero-multiplied expressions.</p></div></div><div class="rule">A division/modulo instruction can die only when its denominator is proven to be a nonzero constant. Unknown denominators remain observable.</div></section>
<section id="measurements"><div class="eyebrow">03 / MEASURED LOCALLY</div><h2>Reduced IR, measured execution.</h2><p class="note">{metadata['implementation']} {metadata['python']} Â· {metadata['os']} {metadata['machine']} Â· {metadata['samples_per_engine']} samples Ã— {metadata['iterations_per_sample']} calls per engine Â· shuffled engine order Â· warmed execution</p><img src="charts/execution.png" alt="Measured execution time across five workloads and three engines"><img src="charts/instructions.png" alt="Baseline and optimized instruction counts"></section>
<section id="decision"><div class="eyebrow">04 / INTERPRETING THE RESULTS</div><h2>Compilation has a cost.</h2><table><thead><tr><th>Workload</th><th>Baseline Î¼s</th><th>Optimized Î¼s</th><th>VM speedup</th><th>Calls to amortize vs tree*</th></tr></thead><tbody>{rows}</tbody></table><p class="note">*Illustrative estimate: separately measured compile-plus-optimize cost divided by per-call savings against the tree interpreter. Parsing excluded. No native machine code is generated.</p><div class="grid"><div class="panel"><h3>Keep</h3><p>Conservative trap preservation and a reference evaluator. Correctness remains independently testable when optimization passes change.</p></div><div class="panel"><h3>Limit</h3><p>Synthetic straight-line workloads intentionally expose optimizations. These microbenchmarks do not measure a general-purpose compiler, CPU-pinned production workload or real-world speedup.</p></div></div></section><footer>AI-assisted portfolio study. Actual local measurements; synthetic workloads. Raw samples, source, tests, environment metadata and IR listings are included in the repository. Recorded {metadata['recorded_at_utc']}.</footer></main></html>'''
    from report_layout import responsive
    report = responsive(report)
    (docs/'report.html').write_text(report,encoding='utf-8')


if __name__ == '__main__':
    main()
