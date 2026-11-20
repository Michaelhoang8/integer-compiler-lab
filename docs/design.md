# Language and optimization design

## Grammar

```text
program   := ("input" NAME ";")* ("let" NAME "=" expr ";")* "return" expr ";"
expr      := additive
additive  := product (("+" | "-") product)*
product   := unary (("*" | "//" | "%") unary)*
unary     := ("+" | "-") unary | NUMBER | NAME | "(" expr ")"
comment   := "#" characters-until-newline
```

Inputs appear before lets, and return terminates the program. Names are unique. A let expression can reference only earlier bindings and declared inputs. Binary operators associate left to right; unary signs bind more tightly than multiplication.

## Observable behavior

All declared inputs are validated, in declaration order, before evaluating any expression. Values must be Python integers exactly; booleans, floats and strings are rejected. Extra mapping entries are ignored. Missing input is a `ValueError`; invalid input type is a `TypeError`.

Let bindings execute eagerly in source order, even when unused. The left operand executes before the right operand. Integers are unbounded; division rounds toward negative infinity and remainder follows the divisor's sign. Division and modulo by zero raise `ZeroDivisionError`, with the interpreter's operation-specific message. Tests compare both exception type and message when relevant.

Resource exhaustion is outside the equivalence contract. Eliminating huge but unused arithmetic can change memory use or recursion behavior; no claim is made about preserving `MemoryError`, process termination or execution time. Unbounded integers means no fixed-width overflow semantics; practical host limits still apply. In particular, CPython's default decimal-string conversion limit restricts extremely long integer literals, and nested source expressions are subject to the interpreter's recursion limit.

## Representation

`Expr`, `Program`, `Instruction` and `Code` are frozen dataclasses. Source names become SSA-like register aliases; each instruction destination is assigned once. Register references point backward. The representation is a straight-line IR, not a control-flow SSA implementation with phi nodes.

An input declaration remains in `Code.inputs` even if its register is removed. Therefore optimization cannot hide missing or incorrectly typed inputs. The optimized IR retains original register numbers for readable before/after comparison; holes are allowed.

## Pass sequence

1. **Constant propagation/folding:** resolve aliased operands and evaluate operations when every operand is constant. Division/modulo by zero is deliberately left as an executable instruction.
2. **Identities:** simplify addition/subtraction of zero, multiplication/division by one and multiplication by zero. The already-lowered operand instructions remain available for the later liveness pass.
3. **Value numbering:** identical immutable operations share an earlier result. Commutative addition/multiplication use canonical operand order. Operand-producing instructions have already executed, so this does not reorder evaluation or traps.
4. **Dead instructions:** seed liveness with the result and every division/modulo whose denominator is unknown or zero. Walk instructions backward to retain dependencies of each live root.

An instruction such as `(x // y) * 0` may simplify to zero, but its division remains live. A division by a known nonzero constant can be removed if its result is unused. A repeated division can share an earlier result: if the denominator is zero, the first instance still traps at its original point.

Pass counters overlap: a constant-folded instruction can subsequently merge with another constant and disappear. They count rewrite events, not disjoint instruction populations.

## Why this architecture

The reference interpreter is deliberately independent of IR generation and optimization. Comparing only the baseline and optimized VM would miss a lowering defect shared by both paths. Randomized tests additionally calculate expected values with ordinary Python integer expressions for selected operator grammars.

An optimizer that aggressively deletes all unreachable results is shorter. Its behavior is incorrect for this eager language. Retaining potentially trapping instructions makes the rule explicit and reviewable without requiring theorem proving or range analysis.

## Next engineering steps

Useful extensions would require additional design, not just more rewrite rules: source spans for diagnostics, a verified IR loader, bounded parser depth, a native backend, control-flow graphs and range analysis for provably nonzero divisors. None are claimed as implemented.
