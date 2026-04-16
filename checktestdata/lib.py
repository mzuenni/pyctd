import os
import re
import sys
from collections import Counter
from enum import Enum
from fractions import Fraction
from functools import cache

if hasattr(sys, "set_int_max_str_digits"):
    sys.set_int_max_str_digits(0)


def _decode_unsafe(raw):
    out = []
    for byte in raw:
        if byte == 0x0A:
            # newline
            out.append("\u21a9")
        elif byte == 0x20:
            # space
            out.append("\u2423")
        elif 0x00 <= byte <= 0x1F:
            # control characters
            out.append(chr(0x2400 + byte))
        elif byte == 0x7F:
            # del
            out.append("\u2421")
        else:
            # latin1 encoding
            out.append(chr(byte))
            # error decoding
            # out.append("\ufffd")
    return "".join(out)


_ELLIPSIS = "[\u2026]"


def _crop(text, limit=25):
    if len(text) > limit + len(_ELLIPSIS):
        return text[: limit - len(_ELLIPSIS)] + _ELLIPSIS
    return text


def _format_token(raw, handle_eof=True):
    if raw == b"" and not handle_eof:
        return "``"
    special = {
        b" ": "<SPACE>",
        b"\n": "<NEWLINE>",
        b"": "<EOF>",
    }
    return special.get(raw, f"`{_crop(_decode_unsafe(raw))}`")


class _InputToken:
    def __init__(self, raw, line, column, length):
        self.raw = raw
        self.line = line
        self.column = column
        self.length = length

    def format(self):
        lines = self.raw.split(b"\n")
        line = lines[self.line - 1]
        if self.line < len(lines):
            line += b"\n"
        offset = self.column - 1
        pref = line[:offset]
        part = line[offset : offset + self.length]

        line = _decode_unsafe(line)
        pref = _decode_unsafe(pref)
        part = _decode_unsafe(part)

        highlight = "".join((" " * len(pref), "^", "~" * max(0, len(part) - 1)))
        if self.line < len(lines) and len(highlight) > len(line):
            highlight = highlight[: len(line)]

        if len(part) > 75 + len(_ELLIPSIS):
            line = line[: len(pref) + 75] + _ELLIPSIS
            highlight = highlight[: len(pref) + 75]
        if len(line) > 75 + len(_ELLIPSIS) and len(pref) > 20 + len(_ELLIPSIS):
            line = _ELLIPSIS + line[len(pref) - 20 :]
            highlight = highlight[len(pref) - 20 - len(_ELLIPSIS) :]
        if len(line) > 75 + len(_ELLIPSIS):
            line = line[:75] + _ELLIPSIS
            highlight = highlight[:75]

        return f"{line}\n{highlight}"


class ValidationError(Exception):
    def __init__(self, msg, token=None):
        self.msg = msg
        self.token = token
        if token:
            super().__init__(f"{token.line}:{token.column} {msg}\n{token.format()}")
        else:
            super().__init__(msg)


class Boolean:
    __slots__ = ("value",)

    @staticmethod
    def _check_boolean_type(lhs, rhs):
        if Boolean != rhs.__class__:
            raise TypeError(f"cannot combine Boolean and {rhs.__class__.__name__}")

    def __init__(self, value):
        assert type(value) is bool
        self.value = value

    def __repr__(self):
        return f"Boolean({repr(self.value)})"

    def __str__(self):
        return f"Boolean({self.value})"

    def __bool__(self):
        return self.value

    def __invert__(self):
        return Boolean(not self.value)

    def __and__(self, other):
        Boolean._check_boolean_type(self, other)
        return Boolean(self.value and other.value)

    def __or__(self, other):
        Boolean._check_boolean_type(self, other)
        return Boolean(self.value or other.value)

    def __eq__(self, other):
        raise TypeError(f"unsupported operand type(s) for ==: 'Boolean' and '{other.__class__.__name__}'")

    def __ne__(self, other):
        Value._check_compare_type(self, other)
        raise TypeError(f"unsupported operand type(s) for !=: 'Boolean' and '{other.__class__.__name__}'")


class Value:
    __slots__ = ("value",)

    def __init__(self, value):
        assert self.__class__ != Value
        self.value = value

    def __repr__(self):
        return f"{self.__class__.__name__}({repr(self.value)})"

    def __str__(self):
        return f"{self.__class__.__name__}({self.value})"

    def __invert__(self):
        raise TypeError(f"bad operand type for unary !: '{self.__class__.__name__}'")

    def __pow__(self, other):
        raise TypeError(f"unsupported operand type(s) for ^: '{self.__class__.__name__}' and '{other.__class__.__name__}'")

    @staticmethod
    def _check_compare_type(lhs, rhs):
        if lhs.__class__ != rhs.__class__:
            raise TypeError(f"cannot compare {lhs.__class__.__name__} and {rhs.__class__.__name__}")

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, other):
        Value._check_compare_type(self, other)
        return Boolean(self.value == other.value)

    def __ne__(self, other):
        Value._check_compare_type(self, other)
        return Boolean(self.value != other.value)

    def __lt__(self, other):
        Value._check_compare_type(self, other)
        return Boolean(self.value < other.value)

    def __le__(self, other):
        Value._check_compare_type(self, other)
        return Boolean(self.value <= other.value)

    def __ge__(self, other):
        Value._check_compare_type(self, other)
        return Boolean(self.value >= other.value)

    def __gt__(self, other):
        Value._check_compare_type(self, other)
        return Boolean(self.value > other.value)


class String(Value):
    __slots__ = ()

    def __init__(self, value):
        assert type(value) is bytes
        super().__init__(value)

    def __str__(self):
        return f"String({self.value.decode(errors='replace')})"


class Number(Value):
    __slots__ = ()

    @staticmethod
    def _check_combine_type(lhs, rhs):
        if lhs.__class__ != rhs.__class__:
            raise TypeError(f"cannot combine {lhs.__class__.__name__} and {rhs.__class__.__name__}")

    def __init__(self, value):
        assert type(value) in (int, Fraction)
        super().__init__(value)

    def is_integer(self):
        # we check the type, not the value!
        return type(self.value) is int

    def __index__(self):
        if not self.is_integer():
            raise TypeError("expected integer but got float")
        return self.value

    def __int__(self):
        if not self.is_integer():
            raise TypeError("expected integer but got float")
        return self.value

    def __neg__(self):
        return Number(-self.value)

    def __add__(self, other):
        Number._check_combine_type(self, other)
        return Number(self.value + other.value)

    def __sub__(self, other):
        Number._check_combine_type(self, other)
        return Number(self.value - other.value)

    def __mul__(self, other):
        Number._check_combine_type(self, other)
        return Number(self.value * other.value)

    def __mod__(self, other):
        Number._check_combine_type(self, other)
        if self.is_integer() and other.is_integer():
            res = self.value % other.value
            if res != 0 and (self.value < 0) != (other.value < 0):
                res -= other.value
            return Number(res)
        else:
            # seems to be an error in Checktestdata
            raise TypeError("can only perform modulo on integers")
            # return Number(self.value % other.value)

    def __truediv__(self, other):
        Number._check_combine_type(self, other)
        if self.is_integer() and other.is_integer():
            res = abs(self.value) // abs(other.value)
            if (self.value < 0) != (other.value < 0):
                res = -res
            return Number(res)
        else:
            return Number(self.value / other.value)

    def __pow__(self, other):
        if not other.is_integer() or other.value < 0 or other.value.bit_length() > sys.maxsize.bit_length() + 1:
            raise TypeError("exponent must be an unsigned long")
        return Number(self.value**other.value)


class VarType:
    __slots__ = ("name", "data", "entries", "value_count")

    def __init__(self, name):
        self.name = name
        # in checktestdata <var> = <val> is a shorthand for var[] = <val>
        # in other words: its just another entry in the array
        # (we keep them separated since this is more efficient)
        self.data = None
        self.entries = {}
        self.value_count = Counter()

    def __repr__(self):
        return f"VarType({repr(self.name)})"

    def reset(self):
        self.data = None
        self.entries = {}
        self.value_count = Counter()

    def __getitem__(self, key):
        if key is None:
            if self.data is None:
                raise TypeError(f"{self.name} is not assigned")
            return self.data
        else:
            if key not in self.entries:
                raise TypeError(f"missing key in {self.name}")
            return self.entries[key]

    def __setitem__(self, key, value):
        assert isinstance(value, Value), self.name
        if key is None:
            self.data = value
        else:
            for key_part in key:
                # Checktestdata seems to enforce integers here
                if type(key_part) is not Number or not key_part.is_integer():
                    raise TypeError(f"key for {self.name} must be integer(s)")
            if key in self.entries:
                self.value_count[self.entries[key]] -= 1
            self.entries[key] = value
            self.value_count[value] += 1


class _RegexParserState(Enum):
    EMPTY = 1
    NONEMPTY = 2
    REPEAT = 3


class _RegexParser:
    TOKENIZER = re.compile(rb"\\[(){}[\]*+?|\\^.-]|.", re.DOTALL)

    def __init__(self, raw):
        self.raw = raw
        self.generator = (m.group() for m in _RegexParser.TOKENIZER.finditer(raw))
        self.next = next(self.generator, None)
        self.last = None
        self.pos = 1
        self.checked = []

    def _error(self, msg, pos=None):
        if pos is None:
            pos = self.pos
        raise RuntimeError(f"invalid regex (at position {pos}): {msg}")

    def _peek(self):
        return self.next

    def _pop(self):
        self.last, self.next = self.next, next(self.generator, None)
        self.pos += len(self.last or b"")
        return self.last

    def _consume(self, expected=None, literal=False):
        if self._peek() != expected and expected is not None:
            self._error("unexpected char")
        token = self._pop()
        assert token is not None
        if literal and len(token) == 1:
            token = re.escape(token)
        self.checked.append(token)

    def _parse_charset(self):
        self._consume(b"[")
        if self._peek() == b"^":
            self._consume()
        tmp = []

        def flush_tmp():
            nonlocal tmp
            for token in tmp:
                if token in b"-&~|\\^":
                    token = re.escape(token)
                self.checked.append(token)
            tmp = []

        empty = True
        while self._peek() is not None and self._peek() != b"]":
            if self._peek() == b"[":
                self._error("nested charset?")
            tmp.append(self._pop())
            empty = False

            if len(tmp) >= 3 and tmp[-2] == b"-":
                lhs = tmp[-3]
                rhs = tmp[-1]
                if lhs[-1] > rhs[-1]:
                    pos = self.pos - len(lhs) - 1 - len(rhs)
                    self._error(f"invalid character range [{_decode_unsafe(lhs)}-{_decode_unsafe(rhs)}]", pos)
                tmp = tmp[:-2]
                flush_tmp()
                self.checked.append(b"-")
                tmp = [rhs]
                flush_tmp()
        flush_tmp()

        if empty:
            self._error("empty character set")

        self._consume(b"]")

    def _parse_non_negative_int(self):
        pos = self.pos
        digits = []
        while self._peek() is not None and self._peek() in b"0123456789":
            digits.append(self._peek())
            self._consume()
        if len(digits) > 1 and digits[0] == b"0":
            self._error("range bound has leading zeros", pos)
        return int(b"".join(digits)) if digits else None

    def _parse_repeat(self):
        self._consume(b"{")
        pos = self.pos
        lower = self._parse_non_negative_int()
        if self._peek() == b",":
            self._consume()
            upper = self._parse_non_negative_int()
            if lower is not None and upper is not None and lower > upper:
                self._error(f"invalid range {{{lower},{upper}}}", pos)
        elif lower is None:
            self._error("missing range length", pos)
        self._consume(b"}")

    def _parse(self):
        state = _RegexParserState.EMPTY

        def transition(next):
            nonlocal state
            if next == _RegexParserState.REPEAT:
                if state == _RegexParserState.EMPTY:
                    self._error("nothing to repeat")
                if state == _RegexParserState.REPEAT:
                    self._error("multiple repeats")
            state = next

        while self._peek() is not None and self._peek() != b")":
            token = self._peek()
            if token == b"[":
                transition(_RegexParserState.NONEMPTY)
                self._parse_charset()
            elif token == b"(":
                transition(_RegexParserState.NONEMPTY)
                self._consume(b"(")
                self.checked.append(b"?:")
                self._parse()
                self._consume(b")")
            elif token == b"{":
                transition(_RegexParserState.REPEAT)
                self._parse_repeat()
            elif token in b"*+?":
                transition(_RegexParserState.REPEAT)
                self._consume()
            elif token == b"|":
                transition(_RegexParserState.EMPTY)
                self._consume()
            elif token == b".":
                transition(_RegexParserState.NONEMPTY)
                self._consume()
            else:
                transition(_RegexParserState.NONEMPTY)
                self._consume(literal=True)

    def compile(self):
        self._parse()
        if self._peek() is not None:
            assert self._peek() == b")"
            self._error("unmatched parenthesis")
        return re.compile(b"".join(self.checked), re.DOTALL)


@cache
def _compile_regex(raw):
    return _RegexParser(raw).compile()


def _assert_type(method, arg, t):
    if type(arg) is not t:
        raise TypeError(f"{method} cannot be invoked with {arg.__class__.__name__}")


def _starts_number(text):
    first_digit = 0 if text and 0x30 <= text[0] <= 0x39 else 1
    if first_digit >= len(text):
        # no digits
        return False
    if first_digit + 1 < len(text) and text.startswith(b"0", first_digit):
        # leading zero
        return False
    return True


class _Reader:
    def __init__(self, raw):
        self.raw = raw
        self.pos = 0
        self.line = 1
        self.column = 1
        self.space_tokenizer = re.compile(rb"[\s]|[^\s]*")

    def _advance(self, text):
        self.pos += len(text)
        newlines = text.count(b"\n")
        if newlines > 0:
            self.line += newlines
            self.column = len(text) - text.rfind(b"\n")
        else:
            self.column += len(text)

    def peek_char(self):
        return self.raw[self.pos : self.pos + 1]

    def pop_char_unchecked(self):
        self.column += 1
        self.pos += 1

    def peek_until_space(self):
        return self.space_tokenizer.match(self.raw, self.pos).group()

    def pop_string(self, expected):
        if not self.raw.startswith(expected, self.pos):
            got = self.raw[self.pos : self.pos + len(expected)]
            mismatch = next((i for i, c in enumerate(zip(got, expected)) if c[0] != c[1]), min(len(got), len(expected)))
            msg = f"got: {_format_token(got)}, but expected {_format_token(expected, False)}"
            if expected == b"\n" and got == b"\r":
                msg += ' (use explicit STRING("\\r\\n") for windows newlines)'
            elif mismatch > 5:
                msg += f" (mismatch after {mismatch} chars)"
            token = _InputToken(self.raw, self.line, self.column, len(got))
            raise ValidationError(msg, token)
        self._advance(expected)

    def pop_regex(self, regex):
        match = _compile_regex(regex).match(self.raw, self.pos)
        if not match:
            got = self.peek_until_space()
            msg = f"got: {_format_token(got)}, but expected {_format_token(regex, False)}"
            token = _InputToken(self.raw, self.line, self.column, len(got))
            raise ValidationError(msg, token)
        text = match.group()
        self._advance(text)
        return text

    def pop_base_number(self, sign=b""):
        start = self.pos
        if self.pos < len(self.raw) and self.raw[self.pos] in sign:
            self.pos += 1
        while self.pos < len(self.raw) and 0x30 <= self.raw[self.pos] <= 0x39:
            self.pos += 1
        text = self.raw[start : self.pos]
        self.column += len(text)
        return text


class _Constraints:
    __slots__ = ("file", "entries")

    def __init__(self, file):
        self.file = file
        self.entries = {}

    def log(self, name, value, min_value, max_value):
        if self.file is None or name is None:
            return
        a, b, c, d, e, f = self.entries.get(name, (False, False, value, value, min_value, max_value))
        a |= value == min_value
        b |= value == max_value
        c = min(c, value)
        d = max(d, value)
        e = min(e, min_value)
        f = max(f, max_value)
        self.entries[name] = (a, b, c, d, e, f)

    def write(self):
        if self.file is None:
            return
        lines = []

        def to_string(value):
            if isinstance(value, bool):
                return str(int(value))
            if isinstance(value, Fraction):
                return str(float(value))
            return str(value)

        for name, entries in self.entries.items():
            string = " ".join(map(to_string, entries))
            lines.append(f"{name} {name} {string}\n")
        with open(self.file, "w") as f:
            f.writelines(lines)


_reader = None
_constraints = None
_standalone = __name__ == "__main__"


def init_lib():
    if _standalone:

        def excepthook(exc_type, exc_value, exc_traceback):
            if exc_type == ValidationError:
                print(exc_value, file=sys.stderr)
                os._exit(43)
            else:
                sys.__excepthook__(exc_type, exc_value, exc_traceback)

        sys.excepthook = excepthook

    global _reader, _constraints

    arg = 1
    if arg < len(sys.argv) and sys.argv[arg] == "--constraints_file":
        _constraints = _Constraints(sys.argv[arg + 1])
        arg += 2
    else:
        _constraints = _Constraints(None)

    if arg < len(sys.argv) and sys.argv[arg] != "-":
        with open(sys.argv[arg], "rb") as f:
            raw = f.read()
        arg += 1
    else:
        raw = sys.stdin.buffer.read()
    _reader = _Reader(raw)

    if arg != len(sys.argv):
        raise RuntimeError("Invalid arguments")


def finalize_lib():
    _constraints.write()
    print("testdata ok!")
    if _standalone:
        os._exit(42)


# Methods used by Checktestdata


def MATCH(arg):
    _assert_type("MATCH", arg, String)
    char = _reader.peek_char()
    if not char:
        return Boolean(False)
    return Boolean(char in arg.value)


def ISEOF():
    return Boolean(not _reader.peek_char())


def UNIQUE(arg, *args):
    assert type(arg) is VarType
    if not args:
        return Boolean(arg.value_count[arg.data] == 0 and all(x <= 1 for x in arg.value_count.values()))
    for other in args:
        assert type(other) is VarType
        if (arg.data is None) != (other.data is None):
            raise ValidationError(f"{arg.name} and {other.name} must have the same keys for UNIQUE")
        if arg.entries.keys() != other.entries.keys():
            raise ValidationError(f"{arg.name} and {other.name} must have the same keys for UNIQUE")

    def make_entry(key):
        return (arg[key], *(other[key] for other in args))

    expected = len(arg.entries)
    unique = {make_entry(key) for key in arg.entries.keys()}
    if arg.data is not None:
        expected += 1
        unique.add((arg.data, *(other.data for other in args)))
    return Boolean(len(unique) == expected)


def INARRAY(value, array):
    assert isinstance(value, Value)
    assert type(array) is VarType
    if array.data is not None and array.data == value:
        return Boolean(True)
    return Boolean(array.value_count[value] > 0)


def STRLEN(arg):
    _assert_type("STRLEN", arg, String)
    return Number(len(arg.value))


def SPACE():
    _reader.pop_string(b" ")


def NEWLINE():
    _reader.pop_string(b"\n")


def EOF():
    got = _reader.peek_char()
    if got:
        msg = f"got: {_format_token(got)}, but expected {_format_token(b'')}"
        token = _InputToken(_reader.raw, _reader.line, _reader.column, 1)
        raise ValidationError(msg, token)


def INT(min, max, constraint=None):
    _assert_type("INT", min, Number)
    _assert_type("INT", max, Number)
    # checktestdata is strict with the parameter type
    if not min.is_integer() or not max.is_integer():
        raise TypeError("INT expected integer but got float")
    line, column = _reader.line, _reader.column
    raw = _reader.pop_base_number(b"-")
    if not _starts_number(raw) or raw.startswith(b"-0"):
        if raw == b"":
            raw = _reader.peek_char()
        token = _InputToken(_reader.raw, line, column, len(raw))
        raise ValidationError(f"expected an integer but got {_format_token(raw)}", token)
    value = int(raw)
    if not min.value <= value <= max.value:
        token = _InputToken(_reader.raw, line, column, len(raw))
        raise ValidationError(f"integer {raw.decode()} outside of range [{min.value}, {max.value}]", token)
    _constraints.log(constraint, value, min.value, max.value)
    return Number(value)


class FLOAT_OPTION(Enum):
    ANY = 0
    FIXED = 1
    SCIENTIFIC = 2

    def msg(self):
        return "float" if self == FLOAT_OPTION.ANY else f"{self.name.lower()} float"


def FLOAT(min, max, constraint=None, option=FLOAT_OPTION.ANY):
    assert type(option) is FLOAT_OPTION
    _assert_type("FLOAT", min, Number)
    _assert_type("FLOAT", max, Number)
    line, column = _reader.line, _reader.column
    raw = _reader.pop_base_number(b"-")
    if not _starts_number(raw):
        if raw == b"":
            raw = _reader.peek_char()
        token = _InputToken(_reader.raw, line, column, len(raw))
        raise ValidationError(f"expected a {option.msg()} but got {_format_token(raw)}", token)
    if _reader.peek_char() == b".":
        _reader.pop_char_unchecked()
        decimals = _reader.pop_base_number(b"")
        raw += b"." + decimals
        if not decimals:
            token = _InputToken(_reader.raw, line, column, len(raw))
            raise ValidationError(f"expected a {option.msg()} but got {_format_token(raw)}", token)
    has_exp = _reader.peek_char() in b"eE"
    if not has_exp and option == FLOAT_OPTION.SCIENTIFIC:
        token = _InputToken(_reader.raw, line, column, len(raw))
        raise ValidationError(f"expected a {option.msg()} but got {_format_token(raw)}", token)
    if has_exp and option != FLOAT_OPTION.FIXED:
        _reader.pop_char_unchecked()
        exponent = _reader.pop_base_number(b"+-")
        raw += b"e" + exponent
        if not _starts_number(exponent):
            token = _InputToken(_reader.raw, line, column, len(raw))
            raise ValidationError(f"expected a {option.msg()} but got {_format_token(raw)}", token)
    text = raw.decode()
    value = Fraction(text)
    if not min.value <= value <= max.value:
        token = _InputToken(_reader.raw, line, column, len(raw))
        raise ValidationError(f"float {text} outside of range [{min.value}, {max.value}]", token)
    if text.startswith("-") and value == 0:
        token = _InputToken(_reader.raw, line, column, len(raw))
        raise ValidationError(f"float {text} should have no sign", token)
    _constraints.log(constraint, value, min.value, max.value)
    return Number(value)


def FLOATP(min, max, mindecimals, maxdecimals, constraint=None, option=FLOAT_OPTION.ANY):
    assert type(option) is FLOAT_OPTION
    _assert_type("FLOATP", min, Number)
    _assert_type("FLOATP", max, Number)
    _assert_type("FLOATP", mindecimals, Number)
    _assert_type("FLOATP", maxdecimals, Number)
    if not mindecimals.is_integer() or mindecimals.value < 0:
        raise TypeError("FLOATP(mindecimals) must be a non-negative integer")
    if not maxdecimals.is_integer() or maxdecimals.value < 0:
        raise TypeError("FLOATP(maxdecimals) must be a non-negative integer")
    line, column = _reader.line, _reader.column
    raw = _reader.pop_base_number(b"-")
    if not _starts_number(raw):
        if raw == b"":
            raw = _reader.peek_char()
        token = _InputToken(_reader.raw, line, column, len(raw))
        raise ValidationError(f"expected a {option.msg()} but got {_format_token(raw)}", token)
    leading = raw[1:] if raw[0:1] == b"-" else raw
    decimals = b""
    if _reader.peek_char() == b".":
        _reader.pop_char_unchecked()
        decimals = _reader.pop_base_number(b"")
        raw += b"." + decimals
        if not decimals:
            token = _InputToken(_reader.raw, line, column, len(raw))
            raise ValidationError(f"expected a {option.msg()} but got {_format_token(raw)}", token)
    has_exp = _reader.peek_char() in b"eE"
    if not has_exp and option == FLOAT_OPTION.SCIENTIFIC:
        token = _InputToken(_reader.raw, line, column, len(raw))
        raise ValidationError(f"expected a {option.msg()} but got {_format_token(raw)}", token)
    if has_exp and option != FLOAT_OPTION.FIXED:
        _reader.pop_char_unchecked()
        exponent = _reader.pop_base_number(b"+-")
        raw += b"e" + exponent
        if not _starts_number(exponent):
            token = _InputToken(_reader.raw, line, column, len(raw))
            raise ValidationError(f"expected a {option.msg()} but got {_format_token(raw)}", token)
    if not mindecimals.value <= len(decimals) <= maxdecimals.value:
        token = _InputToken(_reader.raw, line, column, len(raw))
        raise ValidationError(f"float decimals outside of range [{mindecimals.value}, {maxdecimals.value}]", token)
    if has_exp and (len(leading) != 1 or leading == b"0"):
        token = _InputToken(_reader.raw, line, column, len(raw))
        raise ValidationError("scientific float should have exactly one non-zero before the decimal dot", token)
    text = raw.decode()
    value = Fraction(text)
    if not min.value <= value <= max.value:
        token = _InputToken(_reader.raw, line, column, len(raw))
        raise ValidationError(f"float {text} outside of range [{min.value}, {max.value}]", token)
    if text.startswith("-") and value == 0:
        token = _InputToken(_reader.raw, line, column, len(raw))
        raise ValidationError(f"float {text} should have no sign", token)
    _constraints.log(constraint, value, min.value, max.value)
    return Number(value)


def STRING(arg):
    _assert_type("STRING", arg, String)
    _reader.pop_string(arg.value)


def REGEX(arg):
    _assert_type("REGEX", arg, String)
    return String(_reader.pop_regex(arg.value))


def ASSERT(arg):
    _assert_type("ASSERT", arg, Boolean)
    if not arg.value:
        raise ValidationError("ASSERT failed!")


def UNSET(*args):
    for arg in args:
        _assert_type("UNSET", arg, VarType)
        arg.reset()
