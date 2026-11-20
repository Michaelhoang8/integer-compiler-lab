"""A deliberately small compiler with an executable integer-language specification.

All inputs are validated before execution. Let bindings are immutable and evaluated
eagerly in source order. Integers have arbitrary precision; // floors toward minus
infinity and % follows the divisor's sign. Division by zero is observable even in
an otherwise unused binding. No eval/exec or Python AST is used to parse programs.
"""
from dataclasses import dataclass
import operator
import re
from typing import Mapping


class LanguageError(ValueError):
    """A source-level syntax or binding error."""


@dataclass(frozen=True)
class Expr:
    kind: str
    value: int | str | None = None
    args: tuple['Expr', ...] = ()


@dataclass(frozen=True)
class Program:
    inputs: tuple[str, ...]
    bindings: tuple[tuple[str, Expr], ...]
    result: Expr


@dataclass(frozen=True)
class Instruction:
    dest: int
    op: str
    args: tuple[int, ...] = ()
    literal: int | str | None = None


@dataclass(frozen=True)
class Code:
    inputs: tuple[str, ...]
    instructions: tuple[Instruction, ...]
    result: int


@dataclass(frozen=True)
class Optimization:
    code: Code
    counts: tuple[tuple[str, int], ...]


TOKEN = re.compile(r'\s+|\#[^\n]*|//|[0-9]+|[A-Za-z_][A-Za-z_0-9]*|[+*%()=;\-]')
OPERATIONS = {'+': operator.add, '-': operator.sub, '*': operator.mul,
              '//': operator.floordiv, '%': operator.mod}
PRECEDENCE = {'+': 10, '-': 10, '*': 20, '//': 20, '%': 20}
RESERVED = {'input', 'let', 'return'}


def tokenize(source: str) -> list[str]:
    tokens = []
    offset = 0
    while offset < len(source):
        match = TOKEN.match(source, offset)
        if not match:
            line = source.count('\n', 0, offset) + 1
            raise LanguageError(f'Unexpected character {source[offset]!r} on line {line}')
        token = match.group()
        if not token.isspace() and not token.startswith('#'):
            tokens.append(token)
        offset = match.end()
    return tokens


class Parser:
    def __init__(self, source: str):
        self.tokens = tokenize(source)
        self.pos = 0
        self.bound: set[str] = set()

    def peek(self) -> str:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else '<end>'

    def pop(self, expected: str | None = None) -> str:
        token = self.peek()
        if token == '<end>' or expected is not None and token != expected:
            raise LanguageError(f'Expected {expected or "token"}, got {token!r} at token {self.pos}')
        self.pos += 1
        return token

    def name(self) -> str:
        token = self.pop()
        if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', token) or token in RESERVED:
            raise LanguageError(f'Invalid binding name {token!r}')
        if token in self.bound:
            raise LanguageError(f'Duplicate binding {token!r}')
        return token

    def expression(self, minimum: int = 0) -> Expr:
        token = self.pop()
        if token.isdigit():
            left = Expr('const', int(token))
        elif token in ('-', '+'):
            child = self.expression(30)
            left = Expr('neg', args=(child,)) if token == '-' else child
        elif token == '(':
            left = self.expression()
            self.pop(')')
        elif token in self.bound:
            left = Expr('name', token)
        else:
            raise LanguageError(f'Expected expression or bound name, got {token!r}')
        while PRECEDENCE.get(self.peek(), -1) >= minimum:
            op = self.pop()
            right = self.expression(PRECEDENCE[op] + 1)
            left = Expr(op, args=(left, right))
        return left

    def parse(self) -> Program:
        inputs = []
        bindings = []
        while self.peek() == 'input':
            self.pop('input')
            name = self.name()
            self.pop(';')
            self.bound.add(name)
            inputs.append(name)
        while self.peek() == 'let':
            self.pop('let')
            name = self.name()
            self.pop('=')
            expr = self.expression()
            self.pop(';')
            self.bound.add(name)
            bindings.append((name, expr))
        self.pop('return')
        result = self.expression()
        self.pop(';')
        if self.peek() != '<end>':
            raise LanguageError('Statements after return are not allowed')
        return Program(tuple(inputs), tuple(bindings), result)


def parse(source: str) -> Program:
    return Parser(source).parse()


def validate_inputs(names: tuple[str, ...], values: Mapping[str, int]) -> dict[str, int]:
    result = {}
    for name in names:
        if name not in values:
            raise ValueError(f'Missing input: {name}')
        if type(values[name]) is not int:
            raise TypeError(f'Input {name} must be an integer')
        result[name] = values[name]
    return result


def evaluate(program: Program, values: Mapping[str, int]) -> int:
    """Reference tree interpreter, independent of lowering and optimization."""
    env = validate_inputs(program.inputs, values)

    def visit(expr: Expr) -> int:
        if expr.kind == 'const':
            return expr.value
        if expr.kind == 'name':
            return env[expr.value]
        if expr.kind == 'neg':
            return -visit(expr.args[0])
        # Explicit order: the left operand is evaluated before the right.
        left = visit(expr.args[0])
        right = visit(expr.args[1])
        return OPERATIONS[expr.kind](left, right)

    for name, expr in program.bindings:
        env[name] = visit(expr)
    return visit(program.result)


def compile_program(program: Program) -> Code:
    instructions = []
    env = {}

    def emit(op, args=(), literal=None):
        dest = len(instructions)
        instructions.append(Instruction(dest, op, args, literal))
        return dest

    def visit(expr):
        if expr.kind == 'const':
            return emit('const', literal=expr.value)
        if expr.kind == 'name':
            return env[expr.value]
        return emit(expr.kind, tuple(visit(arg) for arg in expr.args))

    for name in program.inputs:
        env[name] = emit('input', literal=name)
    for name, expr in program.bindings:
        env[name] = visit(expr)
    result = visit(program.result)
    return Code(program.inputs, tuple(instructions), result)


def execute(code: Code, values: Mapping[str, int]) -> int:
    inputs = validate_inputs(code.inputs, values)
    registers = [0] * (max(i.dest for i in code.instructions) + 1)
    for inst in code.instructions:
        if inst.op == 'const':
            value = inst.literal
        elif inst.op == 'input':
            value = inputs[inst.literal]
        elif inst.op == 'neg':
            value = -registers[inst.args[0]]
        else:
            value = OPERATIONS[inst.op](registers[inst.args[0]], registers[inst.args[1]])
        registers[inst.dest] = value
    return registers[code.result]


def optimize(code: Code) -> Optimization:
    """Fold, simplify and value-number, then eliminate only nontrapping dead work.

    Input validation remains based on code.inputs even if an input register dies.
    Every possible division/modulo-by-zero instruction is a liveness root. This
    preserves eager traps in unused bindings and inside expressions like (x//y)*0.
    """
    aliases: dict[int, int] = {}
    constants: dict[int, int] = {}
    available: dict[tuple, int] = {}
    instructions: list[Instruction] = []
    counts = {'constant_fold': 0, 'identity': 0, 'common_subexpression': 0, 'dead_instruction': 0}

    for old in code.instructions:
        args = tuple(aliases[a] for a in old.args)
        op, literal = old.op, old.literal
        all_constant = bool(args) and all(a in constants for a in args)
        safe_fold = op not in ('//', '%') or constants.get(args[1], 0) != 0
        if all_constant and safe_fold:
            literal = -constants[args[0]] if op == 'neg' else OPERATIONS[op](*(constants[a] for a in args))
            op, args = 'const', ()
            counts['constant_fold'] += 1
        target = None
        if op in ('+', '-', '*', '//'):
            left, right = args
            if op in ('+', '-') and constants.get(right) == 0:
                target = left
            elif op == '+' and constants.get(left) == 0:
                target = right
            elif op in ('*', '//') and constants.get(right) == 1:
                target = left
            elif op == '*' and constants.get(left) == 1:
                target = right
            elif op == '*' and (constants.get(left) == 0 or constants.get(right) == 0):
                target = left if constants.get(left) == 0 else right
        if target is not None:
            aliases[old.dest] = target
            counts['identity'] += 1
            continue
        # Operands have already been evaluated. Canonicalizing their register order
        # cannot reorder a trap and is valid for unbounded integer addition/multiply.
        if op in ('+', '*'):
            args = tuple(sorted(args))
        key = (op, args, literal)
        if key in available:
            aliases[old.dest] = available[key]
            counts['common_subexpression'] += 1
            continue
        inst = Instruction(old.dest, op, args, literal)
        instructions.append(inst)
        aliases[old.dest] = old.dest
        available[key] = old.dest
        if op == 'const':
            constants[old.dest] = literal

    live = {aliases[code.result]}
    for inst in instructions:
        if inst.op in ('//', '%') and constants.get(inst.args[1], 0) == 0:
            live.add(inst.dest)
    kept = []
    for inst in reversed(instructions):
        if inst.dest in live:
            kept.append(inst)
            live.update(inst.args)
        else:
            counts['dead_instruction'] += 1
    optimized = Code(code.inputs, tuple(reversed(kept)), aliases[code.result])
    return Optimization(optimized, tuple(counts.items()))


def disassemble(code: Code) -> str:
    lines = []
    for inst in code.instructions:
        args = ', '.join(f'%{arg}' for arg in inst.args)
        if inst.op in ('const', 'input'):
            args = str(inst.literal)
        lines.append(f'%{inst.dest:03d} = {inst.op} {args}'.rstrip())
    lines.append(f'return %{code.result}')
    return '\n'.join(lines) + '\n'
