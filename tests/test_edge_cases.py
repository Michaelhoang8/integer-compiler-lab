"""Independent semantic checks for optimized execution.

The random oracle evaluates locally generated Python arithmetic expressions in
source order; it does not use the compiler's parser, tree visitor or VM helpers.
"""
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from integer_compiler.core import (
    LanguageError, compile_program, evaluate, execute, optimize, parse,
)


def outcome(operation):
    try:
        return ("value", operation())
    except Exception as exc:
        return ("exception", type(exc).__name__, str(exc))


class EdgeCaseChecks(unittest.TestCase):
    def assert_engines_agree(self, source, inputs, expected):
        program = parse(source)
        unoptimized = compile_program(program)
        optimized = optimize(unoptimized).code
        for name, run in [
            ("tree", lambda: evaluate(program, inputs)),
            ("vm", lambda: execute(unoptimized, inputs)),
            ("optimized", lambda: execute(optimized, inputs)),
        ]:
            with self.subTest(engine=name, source=source, inputs=inputs):
                self.assertEqual(expected, outcome(run))

    def test_unused_and_masked_traps_remain_observable(self):
        examples = [
            "input x; let unused = 12 // x; return 9;",
            "input x; let unused = 12 % x; return 9;",
            "input x; return (12 // x) * 0;",
            "input x; return 0 * (12 % x);",
            "input x; let a = 12 // x; return a - a;",
            "input x; let a = 12 % x; let b = 12 % x; return 0;",
            "input x; let a = 12 // x; let b = a * 0; return b + 1;",
            "input x; let unused = 1 // (x * 0); return x;",
        ]
        for source in examples:
            expected = outcome(lambda: evaluate(parse(source), {"x": 0}))
            self.assertEqual(expected[:2], ("exception", "ZeroDivisionError"))
            self.assert_engines_agree(source, {"x": 0}, expected)

    def test_trap_order_uses_eager_source_and_operand_order(self):
        # Division and modulo have distinct Python exception messages, making
        # reordering visible even though both raise ZeroDivisionError.
        cases = [
            ("let a = 1 % 0; let b = 1 // 0; return 7;", lambda: 1 % 0),
            ("let a = 1 // 0; let b = 1 % 0; return 7;", lambda: 1 // 0),
            ("return (1 % 0) + (1 // 0);", lambda: 1 % 0),
            ("return (1 // 0) * (1 % 0);", lambda: 1 // 0),
            ("let a = 2 % 0; return (9 // 0) * 0;", lambda: 2 % 0),
        ]
        for source, oracle in cases:
            self.assert_engines_agree(source, {}, outcome(oracle))

    def test_dead_input_still_requires_upfront_validation(self):
        source = "input first; input second; let trap = 1 // 0; return 7;"
        for inputs, expected in [
            ({}, ("exception", "ValueError", "Missing input: first")),
            ({"first": 2}, ("exception", "ValueError", "Missing input: second")),
            ({"first": True, "second": 2},
             ("exception", "TypeError", "Input first must be an integer")),
            ({"first": 2, "second": 2.0},
             ("exception", "TypeError", "Input second must be an integer")),
        ]:
            self.assert_engines_agree(source, inputs, expected)

    def test_negative_floor_and_remainder_semantics(self):
        for left in [-101, -7, -1, 0, 1, 7, 101]:
            for right in [-7, -2, -1, 1, 2, 7]:
                for op in ["//", "%"]:
                    source = f"input x; input y; return x {op} y;"
                    expected = left // right if op == "//" else left % right
                    self.assert_engines_agree(source, {"x": left, "y": right},
                                              ("value", expected))

    def test_large_integer_and_precedence(self):
        huge = 10 ** 120 + 13
        self.assert_engines_agree(
            "input x; return (x * x + 1) // -3;", {"x": huge},
            ("value", (huge * huge + 1) // -3),
        )
        for expression in [
            "-7 // 3", "20 // 3 // 2", "- - -5", "2 + 3 * 4",
            "(2 + 3) * 4", "7 - 5 - 3", "- (2 + 3) * +4",
        ]:
            self.assert_engines_agree("return " + expression + ";", {},
                                      ("value", eval(expression, {"__builtins__": {}})))

    def test_invalid_syntax_and_binding(self):
        for source in [
            "return 1 / 2;", "return 1 ** 2;", "return x;",
            "let x = x + 1; return x;", "input x; input x; return x;",
            "input x; let x = 1; return x;", "let return = 1; return 0;",
            "return 1; return 2;", "return 1", "return (1 + 2;",
            "return 1.2;", "input 1x; return 1;", "",
        ]:
            with self.subTest(source=source), self.assertRaises(LanguageError):
                parse(source)

    def test_generated_programs_against_independent_python_oracle(self):
        rng = random.Random(20261120)
        symbols = ["+", "-", "*", "//", "%"]

        def expression(names, depth):
            if depth == 0 or rng.random() < .28:
                return rng.choice(names + [str(rng.randint(-5, 5))])
            if rng.random() < .16:
                return "-(" + expression(names, depth - 1) + ")"
            return ("(" + expression(names, depth - 1) + " " + rng.choice(symbols)
                    + " " + expression(names, depth - 1) + ")")

        for program_id in range(160):
            names = ["x", "y", "z"]
            bindings = []
            for i in range(rng.randint(0, 6)):
                bindings.append((f"a{i}", expression(names, 3)))
                names.append(f"a{i}")
            result = expression(names, 3)
            source = "input x; input y; input z;\n"
            source += "\n".join(f"let {name} = {expr};" for name, expr in bindings)
            source += "\nreturn " + result + ";"
            program = parse(source)
            code = compile_program(program)
            optimized = optimize(code).code
            for case_id in range(12):
                inputs = {name: rng.randint(-9, 9) for name in ["x", "y", "z"]}

                def oracle():
                    env = dict(inputs)
                    for name, expr in bindings:
                        env[name] = eval(expr, {"__builtins__": {}}, env)
                    return eval(result, {"__builtins__": {}}, env)

                expected = outcome(oracle)
                for name, run in [
                    ("tree", lambda: evaluate(program, inputs)),
                    ("vm", lambda: execute(code, inputs)),
                    ("optimized", lambda: execute(optimized, inputs)),
                ]:
                    with self.subTest(program=program_id, case=case_id, engine=name):
                        self.assertEqual(expected, outcome(run), source)


if __name__ == "__main__":
    unittest.main()
