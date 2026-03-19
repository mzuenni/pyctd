# Python Checktestdata

> Checktestdata is a tool to verify the syntactical integrity of test cases in programming contests like the ACM ICPC.
> It allows you to specify a simple grammar for your testdata input files, according to which the testdata is checked.
>
> — [Checktestdata](https://github.com/DOMjudge/checktestdata)

This is a Python 3.10 compatible reimplementation of the checktestdata program.

> [!NOTE]
> As of now, the python implementation only supports strict file validation. The arguments `whitespace-ok` and `generate` are not supported.

## Documentation

* [Introduction to the Checktestdata Language](doc/introduction.md).
* The [CTD language specification](https://github.com/DOMjudge/checktestdata/blob/main/doc/format-spec.md) at the
[DOMjudge Checktestdata repository](https://github.com/DOMjudge/checktestdata).

## Installation

Requirements:
 * PyPy >= v7.3.15 (preferred)
 * CPython >= 3.10 (alternative)

The package can be installed directly from [pypi](https://pypi.org/project/checktestdata/):
```
pypy3 -m ensurepip
pypy3 -m pip install checktestdata
```
```
pip install checktestdata
```

## Use

You can use this program to run `.ctd` validators in the same way as the checktestdata binary:
```
pyctd validator.ctd [-d | --debug] < testcase
```

You can also use the programm to convert `.ctd` files into standalone python applications:
```
pyctd validator.ctd --convert [name] [-d | --debug]
```

> [!TIP]
> The generated validator might not be easy to read, cosider adding `-d` to include the original code as comments.

## Extensions

This checktesdata implementation supports the `--constraints_file` argument and can be used with [BAPCtools](https://github.com/RagnarGrootKoerkamp/BAPCtools) to check the constraints of a problem.
