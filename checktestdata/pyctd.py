import argparse
import re
import sys
import traceback
from pathlib import Path

from checktestdata.lib import ValidationError
from checktestdata.parser import parse, Command, ParserException
from checktestdata.tokenizer import tokenize

GENERATED_DEBUG_NAME = "<convertd from ctd>"

def parse_args():
	parser = argparse.ArgumentParser(description="Checktestdata tool written in Python.")
	parser.add_argument(
		"ctd_file",
		metavar="ctd_file",
		type=Path,
		help="The .ctd checker source file"
	)
	parser.add_argument(
		"--debug",
		"-d",
		action="store_true",
		help="Print debug messages",
	)
	parser.add_argument(
		"--convert",
		"-c",
		nargs="?",
		const=True,
		default=None,
		type=Path,
		help="Print debug messages",
	)
	parser.add_argument(
		"--constraints_file",
		default=None,
		type=Path,
		required=False,
		help="The file to write constraints to file to use.",
	)

	args = parser.parse_args()
	if args.convert is True:
		args.convert = args.ctd_file.with_suffix(".py")

	return args

def main():
	config = parse_args()

	def debug(*args, **kwargs):
		if not config.debug:
			return
		kwargs.setdefault("file", sys.stderr)
		print(*args, **kwargs)

	try:
		debug(f"Reading: {config.ctd_file}")
		raw_ctd = config.ctd_file.read_text()
		debug(f"Generating tokens")
		tokens = tokenize(raw_ctd)
		debug(f"Parsing tokens")
		parser = parse(tokens, debug_comments = config.debug)
		debug(f"Converting to python code")
		if config.convert is not None:
			python_code = parser.python_code(standalone = True)
			file = config.convert
			debug(f"Writing python code to: {file}")
			file.write_text(python_code)
		else:
			python_code = parser.python_code()
			python_globals = parser.python_globals()
			debug(f"Compiling python code")
			compiled = compile(python_code, GENERATED_DEBUG_NAME, "exec")
			try:
				debug(f"Running compiled code")
				exec(compiled, python_globals)
			except ValidationError as e:
				print(e, file=sys.stderr)
				sys.exit(1)
			except Exception as e:
				print(e, file=sys.stderr)
				for frame in traceback.extract_tb(e.__traceback__):
					if frame.filename == GENERATED_DEBUG_NAME:
						line = parser.guess_line(python_code, frame.lineno)
						if line:
							print(f"Source {line[0].line}:{line[0].column}", file=sys.stderr)
							print("".join(map(str, line)))
						break
				sys.exit(2)
		debug(f"Done")
	except Exception as e:
		traceback.print_exc()
		print(e, file=sys.stderr)
		sys.exit(2)
