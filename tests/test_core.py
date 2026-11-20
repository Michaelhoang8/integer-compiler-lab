from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from integer_compiler import parse, evaluate, compile_program, optimize, execute, LanguageError


class CompilerTests(unittest.TestCase):
    def compare(self, source, values, expected):
        p = parse(source)
        c = compile_program(p)
        self.assertEqual(evaluate(p, values), expected)
        self.assertEqual(execute(c, values), expected)
        self.assertEqual(execute(optimize(c).code, values), expected)

    def test_precedence_associativity_and_negative_numbers(self):
        self.compare('return 8 - 3 - 2 * 2;', {}, 1)
        self.compare('return -7 // 3;', {}, -3)
        self.compare('return 7 % -3;', {}, -2)
        self.compare('return -(3 + 4) * +2;', {}, -14)

    def test_no_host_language_execution(self):
        for source in ['return __import__(os);', 'return 2 ** 3;', 'return x;', 'return 2 / 3;']:
            with self.subTest(source=source), self.assertRaises(LanguageError):
                parse(source)

    def test_binding_rules(self):
        for source in ['input x; input x; return x;', 'let x = x; return x;',
                       'let x = 1; let x = 2; return x;', 'return 1; return 2;',
                       'let return = 1; return 1;', 'input x;']:
            with self.subTest(source=source), self.assertRaises(LanguageError):
                parse(source)

    def test_trap_is_not_removed_with_unused_binding(self):
        p = parse('input x; let dead = 1 // x; return 0;')
        code = optimize(compile_program(p)).code
        self.assertTrue(any(i.op == '//' for i in code.instructions))
        with self.assertRaises(ZeroDivisionError):
            execute(code, {'x': 0})
        self.assertEqual(execute(code, {'x': 3}), 0)

    def test_repeated_terms_are_shared(self):
        p = parse('input x; let a = x * 3; let b = 3 * x; return a + b;')
        base = compile_program(p)
        optimized = optimize(base)
        self.assertLess(len(optimized.code.instructions), len(base.instructions))
        self.assertGreater(dict(optimized.counts)['common_subexpression'], 0)
        self.assertEqual(execute(optimized.code, {'x': 19}), 114)

    def test_optimization_is_idempotent(self):
        p = parse('input x; input y; let a = (x + 0) * (3 + 4); let b = x * 7; return (a+b)//y;')
        first = optimize(compile_program(p)).code
        second = optimize(first).code
        self.assertEqual(first, second)


if __name__ == '__main__':
    unittest.main()
