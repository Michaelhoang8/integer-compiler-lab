"""Run a source file and print its value plus optimized SSA instructions."""
import argparse
import json
from pathlib import Path
from .core import parse, compile_program, optimize, execute, disassemble


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--inputs', default='{}', help='JSON object of integer inputs')
    parser.add_argument('--ir', action='store_true', help='Print optimized register IR')
    args = parser.parse_args()
    code = optimize(compile_program(parse(args.source.read_text(encoding='utf-8')))).code
    if args.ir:
        print(disassemble(code), end='')
    print(json.dumps({'result': execute(code, json.loads(args.inputs))}))


if __name__ == '__main__':
    main()
