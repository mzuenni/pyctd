import argparse
import sys
from pathlib import Path

from checktestdata.__version__ import __version__
from checktestdata.lib import ValidationError
from checktestdata.parser import parse, ParserException
from checktestdata.tokenizer import tokenize


def parse_args():
    parser = argparse.ArgumentParser(description="Checktestdata tool written in Python.")
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=__version__,
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Print debug messages",
    )
    parser.add_argument(
        "-c",
        "--convert",
        metavar="FILE",
        nargs="?",
        const=True,
        default=None,
        type=Path,
        help="Convert a .ctd file into a standalone python program",
    )
    parser.add_argument(
        "--constraints_file",
        metavar="FILE",
        default=None,
        required=False,
        help="The file to write constraints to file to use.",
    )
    parser.add_argument(
        "program",
        metavar="PROGRAM",
        type=Path,
        help="The .ctd checker source file",
    )
    parser.add_argument(
        "testdata",
        metavar="TESTDATA",
        nargs="?",
        help="If given, the input file to check, or `-` for stdin",
    )

    args = parser.parse_args()
    if args.convert is not None:
        if args.constraints_file is not None:
            parser.error("invalid arguments, cannot combine `--convert` and `--constraints_file`")
        if args.testdata is not None:
            parser.error("invalid arguments, cannot combine `--convert` and `testdata`")
    if args.convert is True:
        args.convert = args.program.with_suffix(".py")
    return args


def standalone_args(config):
    args = [sys.argv[0]]
    if config.constraints_file is not None:
        args += ["--constraints_file", config.constraints_file]
    if config.testdata is not None:
        args += [config.testdata]
    return args


def main():
    config = parse_args()

    def debug(*args, **kwargs):
        if not config.debug:
            return
        kwargs.setdefault("file", sys.stderr)
        print(*args, **kwargs)

    try:
        debug(f"Reading: {config.program}")
        raw_ctd = config.program.read_bytes()
        file_name = str(config.program)
        debug("Generating tokens")
        tokens = tokenize(raw_ctd)
        debug("Parsing tokens")
        sys.setrecursionlimit(10**7)
        parser = parse(tokens, debug_comments=config.debug)
        debug("Converting to python code")
        if config.convert is not None:
            python_code = parser.python_code(standalone=True)
            file = config.convert
            debug(f"Writing python code to: {file}")
            file.write_text(python_code)
        else:
            python_code = parser.python_code()
            python_globals = parser.python_globals()
            debug("Compiling python code")
            compiled = compile(python_code, file_name, "exec")
            try:
                debug("Running compiled code")
                sys.argv = standalone_args(config)
                exec(compiled, python_globals)
            except Exception as e:
                print(e, file=sys.stderr)
                import traceback

                for frame in traceback.extract_tb(e.__traceback__):
                    if frame.filename == file_name:
                        line = parser.guess_line(python_code, frame.lineno)
                        if line:
                            print(f"Source {line[0].line}:{line[0].column}", "".join(map(str, line)), file=sys.stderr)
                        break
                sys.exit(1 if isinstance(e, ValidationError) else 2)
        debug("Done")
    except ParserException as e:
        print(f"{e.token.line}:{e.token.column}", e, file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(e, file=sys.stderr)
        sys.exit(2)
