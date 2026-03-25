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
            case _ if len(text) <= 2 or text[0] in b"0123":
                return bytes((int(text, 8),))
            case _:
                raise ParserException(f"Bad escape sequence '\\{text.decode()}'", token)

    text = ESCAPE_REGEX.sub(replace, token.bytes())
    assert len(text) >= 2
    assert text[0] == ord('"')
    assert text[-1] == ord('"')
    return text[1:-1]


class Comment:
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
    def __init__(self, token, arguments=None):
        self.token = token
        self.arguments = arguments or []

    def __str__(self):
        args = ", ".join([str(arg) for arg in self.arguments])
        parts = [self.token, "(", *args, ")"]
        return "".join(map(str, parts))


class Variable:
    def __init__(self, name, arguments=None):
        self.name = name
        self.arguments = arguments or None

    def __str__(self):
        if self.arguments:
            args = ", ".join(map(str, self.arguments))
            return f"{self.name}[{args},]"
        else:
            # return str(self.token)
            return f"{self.name}[None]"


class Operator:
    PYTHON_OPERATOR = {
        "!": "~",
        "^": "**",
        "&&": " and ",
        "||": " or ",
    }

    def __init__(self, token):
        self.token = token

    def __str__(self):
        op = self.token.text()
        return Operator.PYTHON_OPERATOR.get(op, op)


class Assignment:
    def __init__(self, lhs, rhs):
        self.lhs = lhs if isinstance(lhs, list) else [lhs]
        self.rhs = rhs if isinstance(lhs, list) else [rhs]
        assert len(self.lhs) == len(self.rhs)

    def __str__(self):
        return "; ".join(f"{lhs} = {rhs}" for lhs, rhs in zip(self.lhs, self.rhs))
        # lhs = ", ".join(map(str, self.lhs))
        # rhs = ", ".join(map(str, self.rhs))
        # return f"{lhs} = {rhs}"


class Expression:
    def __init__(self, parts):
        self.parts = parts

    def __str__(self):
        return "".join(map(str, self.parts))


class BlockBegin:
    def __init__(self, command):
        self.command = command

    def __str__(self):
        return f"{self.command}:"


class If:
    def __init__(self, condition):
        self.condition = condition

    def __str__(self):
        return f"if {self.condition}:"


class For:
    def __init__(self, range, variable="_"):
        self.range = range
        self.variable = variable

    def __str__(self):
        return f"for {self.variable} in {self.range}:"


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

    def add_constant(self, token):
        value = None
        match token.type:
            case TokenType.INTEGER:
                value = Number(int(token.bytes()))
            case TokenType.FLOAT:
                value = Number(fractions.Fraction(token.text()))
            case TokenType.STRING:
                value = String(parse_string(token))
            case _:
                assert False
        name = f"const_{len(self.constants)}"
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
        "MATCH": ["_value"],
        "ISEOF": None,
        "UNIQUE": _ellipsis("_varname"),
        "INARRAY": ["_expr", "_varname"],
        # functions
        "STRLEN": ["_value"],
        # commands
        "SPACE": None,
        "NEWLINE": None,
        "EOF": None,
        "INT": ["_expr", "_expr", ["_constraint_variable"]],
        "FLOAT": ["_expr", "_expr", ["_constraint_variable", [TokenType.OPTION]]],
        "FLOATP": ["_expr", "_expr", "_expr", "_expr", ["_constraint_variable", [TokenType.OPTION]]],
        "STRING": ["_value"],
        "REGEX": ["_value", ["_variable"]],
        "ASSERT": ["_test_expr"],
        "SET": _ellipsis("_set_argument"),
        "UNSET": _ellipsis("_varname"),
        # control flow
        "REP": ["_expr", ["_command"]],
        "REPI": ["_variable", "_expr", ["_command"]],
        "WHILE": ["_test_expr", ["_command"]],
        "WHILEI": ["_variable", "_test_expr", ["_command"]],
        "IF": ["_test_expr"],
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

        args = Parser.SIGNATURES[token.text()]
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
        if token.text() == "SET":
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
        name = self.add_variable(token)
        return name

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

    def _value(self):
        token = self.tokens.peek(required=True)
        match token.type:
            case TokenType.STRING | TokenType.INTEGER | TokenType.FLOAT:
                constant = self.add_constant(self.tokens.pop())
                return constant
            case TokenType.VARNAME:
                return self._variable()
            case TokenType.FUNCTION:
                return self._function()
            case _:
                raise ParserException(f"expected expression, but got '{token.text()}'", token)

    OPERATOR_SIGNATURES = (
        (TokenType.MATH, Value),
        (TokenType.COMPARE, Value),
        (TokenType.LOGICAL, Boolean),
    )

    def _parse_expr(self, root_precedence, expected):
        parts = []

        def recurse(precedence):
            nonlocal parts

            token = self.tokens.peek(required=True)
            match token.type:
                case TokenType.OPENPAR:
                    parts.append(self.tokens.pop())
                    lhs = recurse(root_precedence)
                    parts.append(self.tokens.pop(expected_type=TokenType.CLOSEPAR))
                case TokenType.MATH if token.text() == "-":
                    parts.append(Operator(self.tokens.pop()))
                    lhs = recurse(TokenType.MATH.value)
                    if lhs != Value:
                        raise ParserException(f"bad operand type for unary -: '{lhs.__name__}'")
                case TokenType.NOT if expected == Boolean:
                    parts.append(Operator(self.tokens.pop()))
                    lhs = recurse(TokenType.LOGICAL.value)
                    if lhs != Boolean:
                        raise ParserException(f"bad operand type for unary !: '{lhs.__name__}'")
                case TokenType.STRING | TokenType.INTEGER | TokenType.FLOAT:
                    lhs = Value
                    constant = self.add_constant(self.tokens.pop())
                    parts.append(constant)
                case TokenType.VARNAME:
                    lhs = Value
                    parts.append(self._variable())
                case TokenType.FUNCTION:
                    lhs = Value
                    parts.append(self._function())
                case TokenType.TEST if expected == Boolean:
                    lhs = Boolean
                    parts.append(self._test())
                case _:
                    raise ParserException(f"invalid token in expression: '{token.text()}'", token)

            while not self.tokens.empty():
                operator = self.tokens.peek()
                if operator.type not in (TokenType.LOGICAL, TokenType.COMPARE, TokenType.MATH):
                    break
                if operator.type.value < precedence:
                    break
                if (operator.type, lhs) not in Parser.OPERATOR_SIGNATURES:
                    raise TypeError(f"unsupported operand type(s) for {operator}: '{lhs.__name__}' and '?'")
                parts.append(Operator(self.tokens.pop()))
                rhs = recurse(operator.type.value + 1)
                if (operator.type, rhs) not in Parser.OPERATOR_SIGNATURES:
                    raise TypeError(f"unsupported operand type(s) for {operator}: '?' and '{rhs.__name__}'")
                if operator.type == TokenType.COMPARE:
                    lhs = Boolean

            return lhs

        type = recurse(root_precedence)
        if type != expected:
            raise ParserException(f"invalid expression starting with: '{parts[0].text()}'", parts[0])
        return Expression(parts)

    def _expr(self):
        return self._parse_expr(TokenType.MATH.value, Value)

    def _test_expr(self):
        return self._parse_expr(TokenType.LOGICAL.value, Boolean)

    def _parse_block(self, indent):
        token = self.tokens.pop(expected_type=TokenType.CONTROLFLOW)
        args, variable = self._parse_signature(token)

        def handle_block():
            count = self._parse_commands(indent + 1)
            if not count:
                self.add_line(indent + 1, "pass")

        match token.text():
            case "REP" | "REPI":
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
            case "WHILE" | "WHILEI":
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
                self.add_line(indent + 1, If(Expression(["not ", "(", args[0], ")"])))
                self.add_line(indent + 2, "break")
                if len(args) > 1:
                    self.add_line(indent + 1, If(f"{loop_var} > 0"))
                    self.add_line(indent + 2, args[1])
                handle_block()
            case "IF":
                assert variable is None
                self.add_line(indent, If(*args))
                handle_block()
                if self.tokens.has(type=TokenType.ELSE):
                    self.tokens.pop()
                    self.add_line(indent, BlockBegin("else"))
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
                if isinstance(value, (VarType, Value)):
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
