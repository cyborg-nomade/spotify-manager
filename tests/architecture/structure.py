"""Check the project's flat Python conventions without importing source modules."""

import ast


FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def structure_violations(source: str, business: bool) -> list[str]:
    """Find forbidden definitions, comprehensions, signatures and business nesting.

    Args:
        source: Formatted Python source to inspect without executing it.
        business: Also enforce the 25-statement and two-indent business ceilings.

    Returns:
        Source locations and readable reasons for every detected violation.
    """
    violations = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, FUNCTIONS):
            violations.extend(_function_violations(node, business))
        if isinstance(node, COMPREHENSIONS) and _complex_comprehension(node):
            violations.append(f"{node.lineno}: compound or multiline comprehension")
    return violations


def _function_violations(
    function: ast.FunctionDef | ast.AsyncFunctionDef, business: bool
) -> list[str]:
    violations = []
    location = f"{function.lineno}: {function.name}"
    if _has_local_definition(function):
        violations.append(f"{location}: local function or class")
    arguments = function.args
    count = len(arguments.posonlyargs + arguments.args + arguments.kwonlyargs)
    count += int(arguments.vararg is not None) + int(arguments.kwarg is not None)
    if count > 13:
        violations.append(f"{location}: more than 13 parameters")
    if not business:
        return violations
    statements = _executable_statements(function)
    if len(statements) > 25:
        violations.append(f"{location}: more than 25 executable statements")
    if any(statement.col_offset > function.col_offset + 12 for statement in statements):
        violations.append(f"{location}: more than two indentation levels")
    return violations


def _has_local_definition(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(function):
        if node is not function and isinstance(node, (*FUNCTIONS, ast.ClassDef)):
            return True
    return False


def _executable_statements(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.stmt]:
    statements = []
    for node in ast.walk(function):
        if isinstance(node, ast.stmt) and node is not function and not _docstring(node):
            statements.append(node)
    return statements


def _docstring(node: ast.stmt) -> bool:
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Constant):
        return False
    return isinstance(node.value.value, str)


def _complex_comprehension(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
) -> bool:
    return len(node.generators) > 1 or node.lineno != node.end_lineno
