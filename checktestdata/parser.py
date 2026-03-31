import fractions
import re
from itertools import count
from pathlib import Path

import checktestdata.lib
from checktestdata.lib import Boolean, Number, String, Value, VarType
from checktestdata.tokenizer import Token, TokenType


class ParserException(Exception):
    def __init__(self, msg, token):
        super().__init__(msg)
        self.token = token


ESCAPE_REGEX = re.compile(rb'\\([0-7]{1,3}|[\n\\"ntrb])')


def parse_string(token):
    assert token.type == TokenType.STRING

    def replace(match):
        text = match.groups()[0]
        match text:
            case b"\n":
                return b""
            case b"\\" | b'"':
                return text
            case b"n":
                return b"\n"
            case b"t":
                return b"\t"
            case b"r":
                return b"\r"
            case b"b":
                return b"\b"
            case _ if len(text) <= 2 or text[0:1] in b"0123":
                return bytes((int(text, 8),))
            case _:
                raise ParserException(f"Bad escape sequence '\\{text.decode()}'", token)

    text = ESCAPE_REGEX.sub(replace, token.bytes())
    assert len(text) >= 2
    assert text[:1] == b'"'
    assert text[-1:] == b'"'
    return text[1:-1]


class Comment:
    __slots__ = ("tokens",)

    def __init__(self, tokens):
        self.tokens = tokens

    def __str__(self):
        def escape_newline(token):
            if isinstance(token, Token) and token.type == TokenType.STRING:
                raw = f'"{parse_string(token).decode(errors="replace")}"'
            else:
                raw = str(token)
            return raw.replace("\\", "\\\\").replace("\n", "\\n")

        comment = "".join(escape_newline(t) for t in self.tokens)
        return f"#{comment}"


class Command:
    __slots__ = ("token", "arguments")

    def __init__(self, token, arguments=None):
        self.token = token
        self.arguments = arguments or []

    def __str__(self):
        args = ", ".join([str(arg) for arg in self.arguments])
        parts = [self.token, "(", *args, ")"]
        return "".join(map(str, parts))


class Variable:
    __slots__ = ("name", "arguments")

    def __init__(self, name, arguments=None):
        self.name = name
        self.arguments = arguments or None

    def __str__(self):
        if self.arguments:
            args = ", ".join(map(str, self.arguments))
            return f"{self.name}[{args},]"
        else:
            return f"{self.name}[None]"


class Assignment:
    __slots__ = ("lhs", "rhs")

    def __init__(self, lhs, rhs):
        self.lhs = lhs if isinstance(lhs, list) else [lhs]
        self.rhs = rhs if isinstance(lhs, list) else [rhs]
        assert len(self.lhs) == len(self.rhs)

    def __str__(self):
        return "; ".join(f"{lhs} = {rhs}" for lhs, rhs in zip(self.lhs, self.rhs))
        # lhs = ", ".join(map(str, self.lhs))
        # rhs = ", ".join(map(str, self.rhs))
        # return f"{lhs} = {rhs}"


class If:
    __slots__ = ("condition",)

    def __init__(self, condition):
        self.condition = condition

    def __str__(self):
        return f"if {self.condition}:"


class For:
    __slots__ = ("range", "variable")

    def __init__(self, range, variable="_"):
        self.range = range
        self.variable = variable

    def __str__(self):
        return f"for {self.variable} in {self.range}:"


class Operator:
    __slots__ = (
        "ctd",
        "python",
        "function",
        "precedence",
        "in_type",
        "out_type",
    )

    def __init__(self, ctd, python, function, precedence, in_type, out_type):
        self.ctd = ctd
        self.python = python
        self.function = function
        self.precedence = precedence
        self.in_type = in_type
        self.out_type = out_type

    def __str__(self):
        return self.python


class Expression:
    __slots__ = ("lhs", "op", "rhs", "type")

    def __init__(self, type, lhs, op=None, rhs=None):
        assert (op is None) == (rhs is None)
        self.type = type
        self.lhs = lhs
        self.op = op
        self.rhs = rhs

    def is_value(self, type):
        return self.op is None and isinstance(self.lhs, type)

    def __neg__(self):
        if self.type != Value:
            raise TypeError(f"bad operand type for unary -: '{self.type.__name__}'")
        if self.is_value(Number):
            return Expression(Value, -self.lhs)
        return Expression(Value, None, "-", self)

    def __invert__(self):
        if self.type != Boolean:
            raise TypeError(f"bad operand type for unary !: '{self.type.__name__}'")
        if self.is_value(Boolean):
            return Expression(Boolean, ~self.lhs)
        return Expression(Boolean, None, "~", self)

    def binary_operator(lhs, op, rhs):
        if lhs.type != rhs.type or lhs.type != op.in_type:
            raise TypeError(f"unsupported operand type(s) for {op.ctd}: '{lhs.type.__name__}' and '{rhs.type.__name__}'")
        if lhs.is_value(lhs.type) and rhs.is_value(type(lhs.lhs)) and (op.python != "/" or rhs.lhs.value != 0):
            return Expression(op.out_type, op.function(lhs.lhs, rhs.lhs))
        if op.python in "+-*":
            # we intentionally avoid integer division
            ops = "+-" if op.python in "+-" else "*"
            if lhs.op is None or lhs.op in ops:
                if rhs.op is None or rhs.op in ops:
                    value = None
                    variables = []

                    def aggregate(x, sign):
                        nonlocal value
                        if isinstance(x, Number):
                            if value is None:
                                value = Number(0 if ops == "+-" else 1)
                            if ops == "+-" and sign > 0:
                                value += x
                            if ops == "+-" and sign < 0:
                                value -= x
                            if ops == "*":
                                value *= x
                        elif x is not None:
                            variables.append((x, sign))

                    aggregate(lhs.lhs, 1)
                    aggregate(lhs.rhs, -1 if lhs.op == "-" else 1)
                    aggregate(rhs.lhs, -1 if op.python == "-" else 1)
                    aggregate(rhs.rhs, -1 if (op.python == "-") != (rhs.op == "-") else 1)

                    if value is not None:
                        if not variables:
                            return Expression(Value, value)
                        ops = "?" + ops
                        rhs, sign = variables[0]
                        rhs = Expression(Value, rhs)
                        for x, s in variables[1:]:
                            rhs = Expression(Value, rhs, ops[sign * s], x)
                        return Expression(Value, value, ops[sign], rhs)
        return Expression(op.out_type, lhs, op.python, rhs)

    def __str__(self):
        if self.op is None:
            return str(self.lhs)
        elif self.lhs is None:
            return f"{self.op}{self.rhs}"
        else:
            return f"({self.lhs}{self.op}{self.rhs})"


def _ellipsis(*args):
    res = [*args]
    res.append(res)
    return res


class Parser:
    def __init__(self, tokens, debug_comments=False):
        self.tokens = tokens
        self.debug_comments = debug_comments
        self.debug_info = []
        self.lines = None
        self.variables = None
        self.constants = None
        self.rev_constants = None
        self.locals = 0

    def _add_debug_info(self, indent):
        tokens = self.tokens.get_buffered(clear=True)
        if tokens:
            self.debug_info.append((len(self.lines) + 1, tokens))
            if self.debug_comments:
                self.lines.append((indent, Comment([f"{tokens[0].line}:{tokens[0].column} ", *tokens])))

    def add_line(self, indent, line):
        self._add_debug_info(indent)
        self.lines.append((indent, line))

    def add_constant(self, value):
        if value.value is True:
            self.constants["const_true"] = Boolean(True)
            return "const_true"
        elif value.value is False:
            self.constants["const_false"] = Boolean(False)
            return "const_false"
        assert isinstance(value, Value)
        key = (type(value), value.value)
        if key in self.rev_constants:
            name = self.rev_constants[key]
        else:
            name = f"const_{len(self.constants)}"
            self.rev_constants[key] = name
            self.constants[name] = value
        return name

    def add_variable(self, token):
        assert token.type == TokenType.VARNAME
        name = f"var_{token.text()}"
        if name not in self.variables:
            self.variables[name] = VarType(token.text())
        return name

    def get_new_local(self):
        name = f"local_{self.locals}"
        self.locals += 1
        return name

    SIGNATURES = {
        # tests
        b"MATCH": ["_value"],
        b"ISEOF": None,
        b"UNIQUE": _ellipsis("_varname"),
        b"INARRAY": ["_expr", "_varname"],
        # functions
        b"STRLEN": ["_value"],
        # commands
        b"SPACE": None,
        b"NEWLINE": None,
        b"EOF": None,
        b"INT": ["_expr", "_expr", ["_constraint_variable"]],
        b"FLOAT": ["_expr", "_expr", ["_constraint_variable", [TokenType.OPTION]]],
        b"FLOATP": ["_expr", "_expr", "_expr", "_expr", ["_constraint_variable", [TokenType.OPTION]]],
        b"STRING": ["_value"],
        b"REGEX": ["_value", ["_variable"]],
        b"ASSERT": ["_test_expr"],
        b"SET": _ellipsis("_set_argument"),
        b"UNSET": _ellipsis("_varname"),
        # control flow
        b"REP": ["_expr", ["_command"]],
        b"REPI": ["_variable", "_expr", ["_command"]],
        b"WHILE": ["_test_expr", ["_command"]],
        b"WHILEI": ["_variable", "_test_expr", ["_command"]],
        b"IF": ["_test_expr"],
    }

    def _parse_signature(self, token):
        parsed_args = []
        variable = None

        def recurse(args):
            nonlocal variable
            for i, arg in enumerate(args):
                optional = isinstance(arg, list)
                if i == 0:
                    assert not optional
                else:
                    has_more = self.tokens.has(type=TokenType.COMMA)
                    if not has_more and optional:
                        break
                    self.tokens.pop(expected_type=TokenType.COMMA)

                if optional:
                    recurse(arg)
                elif arg == TokenType.OPTION:
                    parsed_args.append(f"FLOAT_OPTION.{self.tokens.pop(expected_type=TokenType.OPTION).text()}")
                elif arg in ["_variable", "_constraint_variable"]:
                    assert variable is None
                    variable = self._variable()
                    if arg == "_constraint_variable":
                        constraint = self.variables[variable.name].name
                        parsed_args.append(repr(constraint))
                elif isinstance(arg, str):
                    parsed_args.append(getattr(self, arg)())
                else:
                    assert False, f"signature error: {arg}"

        args = Parser.SIGNATURES[token.bytes()]
        if args is not None:
            self.tokens.pop(expected_type=TokenType.OPENPAR)
            recurse(args)
            self.tokens.pop(expected_type=TokenType.CLOSEPAR)
        return parsed_args, variable

    def _set_argument(self):
        lhs = self._variable()
        self.tokens.pop(expected_type=TokenType.ASSIGN)
        rhs = self._expr()
        return Assignment(lhs, rhs)

    def _command(self):
        token = self.tokens.pop(expected_type=TokenType.COMMAND)
        args, variable = self._parse_signature(token)
        if token.bytes() == b"SET":
            assert variable is None
            assert all(isinstance(a, Assignment) for a in args)
            lhs = sum([a.lhs for a in args], [])
            rhs = sum([a.rhs for a in args], [])
            command = Assignment(lhs, rhs)
        else:
            command = Command(token, args)
            if variable is not None:
                command = Assignment(variable, command)
        return command

    def _function(self):
        token = self.tokens.pop(expected_type=TokenType.FUNCTION)
        args, variable = self._parse_signature(token)
        assert variable is None
        return Command(token, args)

    def _test(self):
        token = self.tokens.pop(expected_type=TokenType.TEST)
        args, variable = self._parse_signature(token)
        assert variable is None
        return Command(token, args)

    def _varname(self):
        token = self.tokens.pop(expected_type=TokenType.VARNAME)
        return self.add_variable(token)

    def _variable(self):
        token = self.tokens.pop(expected_type=TokenType.VARNAME)
        args = None
        if self.tokens.has(type=TokenType.OPENBRACKET):
            self.tokens.pop()
            args = [self._expr()]
            while self.tokens.has(type=TokenType.COMMA):
                self.tokens.pop()
                args.append(self._expr())
            self.tokens.pop(expected_type=TokenType.CLOSEBRACKET)
        name = self.add_variable(token)
        return Variable(name, args)

    def _value(self, as_constant=True):
        token = self.tokens.peek(required=True)
        value = None
        match token.type:
            case TokenType.STRING:
                value = String(parse_string(self.tokens.pop()))
            case TokenType.INTEGER:
                value = Number(int(self.tokens.pop().bytes()))
            case TokenType.FLOAT:
                value = Number(fractions.Fraction(self.tokens.pop().text()))
            case TokenType.VARNAME:
                return self._variable()
            case TokenType.FUNCTION:
                return self._function()
            case _:
                raise ParserException(f"expected expression, but got '{token.text()}'", token)
        assert value is not None
        return self.add_constant(value) if as_constant else value

    BINARY_OPERATORS = {
        # pow
        b"^": Operator("^", "**", lambda x, y: x**y, 8, Value, Value),
        # Unary Minus: 7
        # multiplication/division/mod
        b"*": Operator("*", "*", lambda x, y: x * y, 6, Value, Value),
        b"/": Operator("/", "/", lambda x, y: x / y, 6, Value, Value),
        b"%": Operator("%", "%", lambda x, y: x % y, 6, Value, Value),
        # addition/subtraction
        b"+": Operator("+", "+", lambda x, y: x + y, 5, Value, Value),
        b"-": Operator("-", "-", lambda x, y: x - y, 5, Value, Value),
        # comparison (checktestdata does not allow any kind of comparison between booleans)
        b"<": Operator("<", "<", lambda x, y: x < y, 4, Value, Boolean),
        b">": Operator(">", ">", lambda x, y: x > y, 4, Value, Boolean),
        b"<=": Operator("<=", "<=", lambda x, y: x <= y, 4, Value, Boolean),
        b">=": Operator(">=", ">=", lambda x, y: x >= y, 4, Value, Boolean),
        b"!=": Operator("!=", "!=", lambda x, y: x != y, 4, Value, Boolean),
        b"==": Operator("==", "==", lambda x, y: x == y, 4, Value, Boolean),
        # logical
        # unary not: 3
        b"&&": Operator("&&", " and ", lambda x, y: x and y, 2, Boolean, Boolean),
        b"||": Operator("||", " or ", lambda x, y: x or y, 1, Boolean, Boolean),
    }

    def _parse_expr(self, expected):
        def recurse(precedence=0):
            token = self.tokens.peek(required=True)
            match token.type:
                case TokenType.OPENPAR:
                    self.tokens.pop()
                    lhs = recurse()
                    self.tokens.pop(expected_type=TokenType.CLOSEPAR)
                case TokenType.MATH if token.bytes() == b"-":
                    self.tokens.pop()
                    lhs = -recurse(7)
                case TokenType.NOT if expected == Boolean:
                    self.tokens.pop()
                    lhs = ~recurse(3)
                case TokenType.STRING | TokenType.INTEGER | TokenType.FLOAT | TokenType.VARNAME | TokenType.FUNCTION:
                    lhs = Expression(Value, self._value(as_constant=False))
                case TokenType.TEST if expected == Boolean:
                    lhs = Expression(Boolean, self._test())
                case _:
                    raise ParserException(f"invalid token in expression: '{token.text()}'", token)

            while not self.tokens.empty():
                operator = Parser.BINARY_OPERATORS.get(self.tokens.peek().bytes())
                if operator is None or operator.precedence < precedence:
                    break
                self.tokens.pop()
                lhs = lhs.binary_operator(operator, recurse(operator.precedence + 1))

            return lhs

        first = self.tokens.peek(required=True)
        expr = recurse()
        if expr.type != expected:
            raise ParserException(f"invalid expression starting with: '{first.text()}'", first)

        nodes = [expr]
        while nodes:
            node = nodes.pop()
            if isinstance(node.lhs, (Value, Boolean)):
                node.lhs = self.add_constant(node.lhs)
            elif isinstance(node.lhs, Expression):
                nodes.append(node.lhs)
            if isinstance(node.rhs, (Value, Boolean)):
                node.rhs = self.add_constant(node.rhs)
            elif isinstance(node.rhs, Expression):
                nodes.append(node.rhs)
        return expr

    def _expr(self):
        return self._parse_expr(Value)

    def _test_expr(self):
        return self._parse_expr(Boolean)

    def _parse_block(self, indent):
        token = self.tokens.pop(expected_type=TokenType.CONTROLFLOW)
        args, variable = self._parse_signature(token)

        def handle_block():
            count = self._parse_commands(indent + 1)
            if not count:
                self.add_line(indent + 1, "pass")

        match token.bytes():
            case b"REP" | b"REPI":
                loop_var = "_"
                local = self.get_new_local()
                """
                local = args[0]
                For _ in range(local):
                    variable = Number(_) #optional:
                    #optional:
                    if _ > 0:
                        args[1]
                variable = Number(local) #optional
                """
                self.add_line(indent, Assignment(local, args[0]))
                self.add_line(indent, For(f"range({local})", loop_var))
                if variable is not None:
                    self.add_line(indent + 1, Assignment(variable, Command("Number", [loop_var])))
                if len(args) > 1:
                    self.add_line(indent + 1, If(f"{loop_var} > 0"))
                    self.add_line(indent + 2, args[1])
                handle_block()
                if variable is not None:
                    self.add_line(indent, Assignment(variable, local))
            case b"WHILE" | b"WHILEI":
                loop_var = "_"
                """
                For _ in count(0):
                    variable = Number(_) #optional
                    if not (args[0]):
                        break
                    #optional:
                    if _ > 0:
                        args[1]
                """
                self.add_line(indent, For("count(0)", loop_var))
                if variable is not None:
                    self.add_line(indent + 1, Assignment(variable, Command("Number", [loop_var])))
                self.add_line(indent + 1, If(f"not ({args[0]})"))
                self.add_line(indent + 2, "break")
                if len(args) > 1:
                    self.add_line(indent + 1, If(f"{loop_var} > 0"))
                    self.add_line(indent + 2, args[1])
                handle_block()
            case b"IF":
                assert variable is None
                self.add_line(indent, If(*args))
                handle_block()
                if self.tokens.has(type=TokenType.ELSE):
                    self.tokens.pop()
                    self.add_line(indent, "else:")
                    handle_block()
            case _:
                assert False
        self.tokens.pop(expected_type=TokenType.END)
        self._add_debug_info(indent)

    def _parse_command(self, indent):
        self.add_line(indent, self._command())

    def _parse_commands(self, indent):
        count = 0
        while not self.tokens.empty():
            token = self.tokens.peek()
            match token.type:
                case TokenType.ELSE | TokenType.END:
                    return count
                case TokenType.CONTROLFLOW:
                    count += 1
                    self._parse_block(indent)
                case TokenType.COMMAND:
                    count += 1
                    self._parse_command(indent)
                case _:
                    raise ParserException(f"expected command, but got '{token.text()}'", token)

    def parse(self):
        if self.lines is None:
            self.lines = []
            self.variables = {}
            self.constants = {}
            self.rev_constants = {}
            self._parse_commands(0)
            if not self.tokens.empty():
                token = self.tokens.peek()
                assert token.type in [TokenType.ELSE, TokenType.END]
                raise ParserException(f"Unmatched '{token.text()}'", token)
            self.add_line(0, Command("EOF"))

    def python_code(self, standalone=False):
        self.parse()
        generated = []
        if standalone:
            generated.append("#" * 80)
            generated.append("# pyctd library functions")
            generated.append("#" * 80)
            generated.append("from itertools import count")
            lib_file = Path(checktestdata.lib.__file__)
            generated.append(lib_file.read_text())

            generated.append("#" * 80)
            generated.append("# constants and variables")
            generated.append("#" * 80)
            for name, value in self.python_globals().items():
                if isinstance(value, (VarType, Value, Boolean)):
                    generated.append(f"{name} = {repr(value)}")
            generated.append("")

        generated.append("#" * 80)
        generated.append("# generated by pyctd")
        generated.append("#" * 80)
        generated.append("init_lib()")
        INDENT = "    "
        for indent, line in self.lines:
            generated.append(f"{INDENT * indent}{line}")
        generated.append("finalize_lib()")
        return "\n".join(generated) + "\n"

    def python_globals(self):
        lib_functions = {name: f for name, f in checktestdata.lib.__dict__.items() if not name.startswith("_")}
        return {
            **lib_functions,
            "count": count,
            **self.constants,
            **self.variables,
        }

    def guess_line(self, code, line):
        if not self.debug_info:
            return None

        start_marker = "\ninit_lib()\n"
        end_marker = "\nfinalize_lib()\n"
        assert start_marker in code
        prefix, code = code.split(start_marker)
        assert end_marker in code
        prefix += start_marker
        line -= prefix.count("\n")

        if line <= 0 or line > len(self.lines):
            return None

        last_info = None
        for debug_line, debug_info in self.debug_info:
            if debug_line > line:
                break
            last_info = debug_info
        return last_info


def parse(tokens, debug_comments=False):
    parser = Parser(tokens, debug_comments=debug_comments)
    parser.parse()
    return parser
