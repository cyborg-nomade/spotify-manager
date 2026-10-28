"""Find named functions and bound methods passed as production execution values."""

import ast
from dataclasses import dataclass

from tests.support.callback_paths import _module_bindings
from tests.support.dependency_paths import _target


@dataclass(frozen=True)
class FunctionArgument:
    """Identify one function-valued call argument without importing production.

    Args:
        owner: Qualified enclosing function or class.
        callee: Original called API expression.
        parameter: Keyword name or positional argument number.
        function: Original function or bound-method expression.
        line: Original call location.
    """

    owner: str
    callee: str
    parameter: str
    function: str
    line: int


def defined_functions(modules: dict[str, ast.Module]) -> set[str]:
    """Resolve module functions and imported reexports across the package.

    Args:
        modules: Parsed production modules.

    Returns:
        Qualified function names including imported aliases.
    """
    known = set()
    for module, tree in modules.items():
        known.update(_module_functions(module, tree))
    while True:
        expanded = _imported_functions(modules, known)
        if expanded == known:
            return known
        known = expanded


def _module_functions(module: str, tree: ast.Module) -> set[str]:
    result = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.add(f"{module}.{node.name}")
    return result


def _imported_functions(modules: dict[str, ast.Module], known: set[str]) -> set[str]:
    result = set(known)
    for module, tree in modules.items():
        result.update(_module_aliases(module, tree, known))
    return result


def _module_aliases(module: str, tree: ast.Module, known: set[str]) -> set[str]:
    result = set()
    bindings = _module_bindings(module, tree)
    for alias, target in bindings.items():
        if target in known:
            result.add(f"{module}.{alias}")
    for node in tree.body:
        result.update(_assigned_functions(module, node, bindings, known))
    return result


def _assigned_functions(
    module: str, node: ast.stmt, bindings: dict[str, str], known: set[str]
) -> set[str]:
    if not isinstance(node, ast.Assign) or _target(node.value, bindings) not in known:
        return set()
    result = set()
    for target in node.targets:
        if isinstance(target, ast.Name):
            result.add(f"{module}.{target.id}")
    return result


def function_arguments(
    module: str, tree: ast.Module, known: set[str]
) -> list[FunctionArgument]:
    """Find literal functions, imported functions, and methods on self or cls.

    Args:
        module: Qualified production module name.
        tree: Parsed module without executing its imports.
        known: Resolved module function names.

    Returns:
        Function-valued arguments, retaining their enclosing scope.
    """
    bindings = _module_bindings(module, tree)
    result = []
    for node in tree.body:
        result.extend(_declaration_arguments(module, node, bindings, known, set()))
    return result


def _declaration_arguments(
    owner: str,
    node: ast.stmt,
    bindings: dict[str, str],
    known: set[str],
    methods: set[str],
) -> list[FunctionArgument]:
    if isinstance(node, ast.ClassDef):
        return _class_arguments(f"{owner}.{node.name}", node, bindings, known)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        bindings = _function_bindings(node, bindings, methods)
        owner = f"{owner}.{node.name}"
    return _scope_arguments(owner, node, bindings, known, methods)


def _class_arguments(
    owner: str, node: ast.ClassDef, bindings: dict[str, str], known: set[str]
) -> list[FunctionArgument]:
    methods = set()
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.add(child.name)
    result = []
    for child in node.body:
        result.extend(_declaration_arguments(owner, child, bindings, known, methods))
    return result


def _function_bindings(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    bindings: dict[str, str],
    methods: set[str],
) -> dict[str, str]:
    result = dict(bindings)
    for child in ast.walk(node):
        if isinstance(child, ast.arg):
            result.pop(child.arg, None)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            result.pop(child.id, None)
    for child in ast.walk(node):
        result.update(_local_assignment(child, result, methods))
    return result


def _local_assignment(
    node: ast.AST, bindings: dict[str, str], methods: set[str]
) -> dict[str, str]:
    if not isinstance(node, ast.Assign):
        return {}
    target = _target(node.value, bindings)
    if isinstance(node.value, ast.Lambda) or _bound_method(node.value, methods):
        target = "<function>"
    result = {}
    for name in node.targets:
        if isinstance(name, ast.Name) and target:
            result[name.id] = target
    return result


def _scope_arguments(
    owner: str,
    node: ast.AST,
    bindings: dict[str, str],
    known: set[str],
    methods: set[str],
) -> list[FunctionArgument]:
    result = []
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        result.extend(_call_arguments(owner, call, bindings, known, methods))
    return result


def _call_arguments(
    owner: str,
    call: ast.Call,
    bindings: dict[str, str],
    known: set[str],
    methods: set[str],
) -> list[FunctionArgument]:
    arguments = [(str(index), value) for index, value in enumerate(call.args)]
    arguments.extend((item.arg or "**", item.value) for item in call.keywords)
    result = []
    for parameter, value in arguments:
        required = (
            _target(call.func, bindings) == "asyncio.to_thread"
            or ast.unparse(call.func) == "executor.submit"
        ) and parameter == "0"
        if not required and not _is_function(value, bindings, known, methods):
            continue
        result.append(
            FunctionArgument(
                owner,
                ast.unparse(call.func),
                parameter,
                ast.unparse(value),
                call.lineno,
            )
        )
    return result


def _is_function(
    value: ast.expr, bindings: dict[str, str], known: set[str], methods: set[str]
) -> bool:
    if isinstance(value, ast.Lambda) or _target(value, bindings) in known | {
        "<function>",
        "asyncio.run",
    }:
        return True
    if not isinstance(value, ast.Attribute) or not isinstance(value.value, ast.Name):
        return False
    return _bound_method(value, methods)


def _bound_method(value: ast.expr, methods: set[str]) -> bool:
    if not isinstance(value, ast.Attribute) or not isinstance(value.value, ast.Name):
        return False
    return value.value.id in {"self", "cls"} and value.attr in methods
