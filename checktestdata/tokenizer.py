import re
from dataclasses import dataclass
from enum import auto, Enum


class TokenType(Enum):
    INTEGER = auto()
    FLOAT = auto()
    STRING = auto()
    VARNAME = auto()
    NOT = auto()
    LOGICAL = auto()
    COMPARE = auto()
    MATH = auto()
    ASSIGN = auto()
    COMMA = auto()
    SPACE = auto()
    OPENBRACKET = auto()
    CLOSEBRACKET = auto()
    OPENPAR = auto()
    CLOSEPAR = auto()
    COMMENT = auto()
    OPTION = auto()
    TEST = auto()
    FUNCTION = auto()
    COMMAND = auto()
    CONTROLFLOW = auto()
    ELSE = auto()
    END = auto()
    UNKNOWN = auto()


@dataclass
class Token:
    raw: bytes
    start: int
    end: int
    line: int
    column: int
    type: TokenType

    def bytes(self):
        return self.raw[self.start : self.end]

    def text(self):
        return self.bytes().decode(errors="replace")

    def __str__(self):
        return self.text()

    def __repr__(self):
        return f"{self.line}:{self.column}:{self.type}{{{self.text()}}}"


class EOFException(Exception):
    pass


class UnexpectedTokenException(Exception):
    def __init__(self, token):
        self.token = token

    def __str__(self):
        return f"unexpected token at {self.token.line}:{self.token.column} '{self.token.text()}'"


class UnknownTokenException(Exception):
    def __init__(self, token):
        self.token = token

    def __str__(self):
        return f"unknown token at {self.token.line}:{self.token.column} '{self.token.text()}'"


class TokenStream:
    def __init__(self, generator):
        self.generator = generator
        self.next = next(self.generator, None)
        self.buffered = []

    def empty(self):
        return self.next is None

    def peek(self):
        return self.next

    def has(self, *, type=None):
        if self.empty():
            return False
        cur = self.peek()
        if type is not None and cur.type != type:
            return False
        return True

    def pop(self, *, expected_type=None):
        res, self.next = self.next, next(self.generator, None)
        if res is None:
            raise EOFException("unexpected end of file")
        if expected_type is not None and res.type != expected_type:
            raise UnexpectedTokenException(res)
        self.buffered.append(res)
        return res

    def get_buffered(self, clear=False):
        res = self.buffered
        if clear:
            self.buffered = []
        return res


def tokenize(raw):
    # some token types are combined in the regex because recognizing them afterwards is easier:
    # - all keywords
    # - integers and floats
    token_regex = {
        "_NUMBER": rb"(?:(?:[0-9]*\.[0-9]+|[0-9]+\.|[0-9]+)(?:[eE][+-]?[0-9]+)?)|(?:0|[1-9][0-9]*)",
        "STRING": rb'"(?:[^"\\]|\\.)*"',
        "_KEYWORD": rb"[A-Z]+",
        "VARNAME": rb"[a-z][a-z0-9]*",
        "COMPARE": rb"<=?|>=?|==|!=",
        "NOT": rb"!",
        "LOGICAL": rb"&&|\|\|",
        "MATH": rb"[+*/%^-]",
        "ASSIGN": rb"=",
        "COMMA": rb",",
        "SPACE": rb"\s",
        "OPENBRACKET": rb"\[",
        "CLOSEBRACKET": rb"\]",
        "OPENPAR": rb"\(",
        "CLOSEPAR": rb"\)",
        "COMMENT": rb"#[^\n]*",
        "UNKNOWN": rb".",
    }
    combined = b"|".join(b"(?P<%s>%s)" % (name.encode(), regex) for name, regex in token_regex.items())
    base_tokenizer = re.compile(combined, re.DOTALL | re.MULTILINE)
    integer_token = re.compile(rb"0|[1-9][0-9]*")

    def keyword_type(keyword):
        match keyword:
            case b"FIXED" | b"SCIENTIFIC":
                return TokenType.OPTION
            case b"MATCH" | b"ISEOF" | b"UNIQUE" | b"INARRAY":
                return TokenType.TEST
            case b"STRLEN":
                return TokenType.FUNCTION
            case b"SPACE" | b"NEWLINE" | b"EOF" | b"INT" | b"FLOAT" | b"FLOATP" | b"STRING" | b"REGEX" | b"ASSERT" | b"SET" | b"UNSET":
                return TokenType.COMMAND
            case b"REP" | b"REPI" | b"WHILE" | b"WHILEI" | b"IF":
                return TokenType.CONTROLFLOW
            case b"ELSE":
                return TokenType.ELSE
            case b"END":
                return TokenType.END
            case _:
                return TokenType.UNKNOWN

    def generator():
        line = 1
        column = 1
        for match in base_tokenizer.finditer(raw):
            base_type = match.lastgroup
            start = match.start()
            end = match.end()
            text = raw[start:end]

            type = TokenType.UNKNOWN
            if base_type == "_KEYWORD":
                type = keyword_type(text)
            elif base_type == "_NUMBER":
                type = TokenType.INTEGER if integer_token.fullmatch(text) else TokenType.FLOAT
            else:
                type = TokenType[base_type]

            token = Token(raw, start, end, line, column, type)

            if type == TokenType.UNKNOWN:
                raise UnknownTokenException(token)

            newline = text.find(b"\n")
            if newline >= 0:
                line += text.count(b"\n")
                column = len(text) - newline
            else:
                column += len(text)

            if type in [TokenType.SPACE, TokenType.COMMENT]:
                continue

            yield token

    # print(*generator())
    return TokenStream(generator())
