"""Audit executable dependencies without importing application or SDK startup."""

import ast
from dataclasses import dataclass
from pathlib import Path

from tests.support.dependency_paths import _import_bindings
from tests.support.dependency_paths import _target


@dataclass(frozen=True)
class CallbackUse:
    """Describe an executable dependency annotation.

    Args:
        owner: Qualified function, method or class.
        parameter: Argument or field receiving a callback.
        annotation: Original annotation text.
        line: One-based declaration line.
    """

    owner: str
    parameter: str
    annotation: str
    line: int


def module_trees(root: Path) -> dict[str, ast.Module]:
    """Read production modules without executing their imports.

    Args:
        root: Repository root.

    Returns:
        Module names mapped to parsed source.
    """
    modules = {}
    for path in sorted((root / "spotify_manager").rglob("*.py")):
        parts = list(path.relative_to(root).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules[".".join(parts)] = ast.parse(path.read_text())
    return modules


def callable_types(modules: dict[str, ast.Module]) -> set[str]:
    """Resolve function aliases across production module imports.

    Args:
        modules: Parsed production modules.

    Returns:
        Qualified callable type aliases and callable protocols.
    """
    known = {"typing.Callable", "collections.abc.Callable"}
    while True:
        expanded = set(known)
        for module, tree in modules.items():
            expanded.update(_defined_types(module, tree, known))
        if expanded == known:
            return known
        known = expanded


def _defined_types(module: str, tree: ast.Module, known: set[str]) -> set[str]:
    result = set()
    bindings = _module_bindings(module, tree)
    for alias, target in bindings.items():
        if target in known:
            result.add(f"{module}.{alias}")
    for node in tree.body:
        name = _callable_declaration(node, bindings, known)
        if name:
            result.add(f"{module}.{name}")
    return result


def _callable_declaration(
    node: ast.stmt, bindings: dict[str, str], known: set[str]
) -> str | None:
    if isinstance(node, ast.TypeAlias) and _is_callback(node.value, bindings, known):
        return node.name.id
    if isinstance(node, ast.Assign) and _is_callback(node.value, bindings, known):
        target = node.targets[0]
        return target.id if isinstance(target, ast.Name) else None
    if isinstance(node, ast.ClassDef) and _has_call_method(node):
        return node.name
    return None


def _has_call_method(node: ast.ClassDef) -> bool:
    for child in node.body:
        if isinstance(child, ast.FunctionDef) and child.name == "__call__":
            return True
    return False


def _is_callback(
    annotation: ast.AST | None, bindings: dict[str, str], known: set[str]
) -> bool:
    if annotation is None:
        return False
    for node in ast.walk(annotation):
        if _target(node, bindings) in known:
            return True
    return False


def callback_uses(source: str, module: str, known: set[str]) -> list[CallbackUse]:
    """Find callback fields and parameters, including imported aliases.

    Args:
        source: Module text.
        module: Qualified module name.
        known: Resolved callable annotation names.

    Returns:
        Function-shaped dependencies in declaration order.
    """
    tree = ast.parse(source)
    bindings = _module_bindings(module, tree)
    uses = []
    for node in tree.body:
        uses.extend(_node_uses(node, module, bindings, known))
    return uses


def _node_uses(
    node: ast.stmt, owner: str, bindings: dict[str, str], known: set[str]
) -> list[CallbackUse]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _function_uses(node, owner, bindings, known)
    if isinstance(node, ast.ClassDef):
        return _class_uses(node, f"{owner}.{node.name}", bindings, known)
    return []


def _function_uses(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: str,
    bindings: dict[str, str],
    known: set[str],
) -> list[CallbackUse]:
    uses = []
    for argument in ast.walk(node.args):
        if not isinstance(argument, ast.arg):
            continue
        if _is_callback(argument.annotation, bindings, known):
            uses.append(_use(f"{owner}.{node.name}", argument.arg, argument))
    return uses


def _class_uses(
    node: ast.ClassDef, owner: str, bindings: dict[str, str], known: set[str]
) -> list[CallbackUse]:
    uses = []
    for child in node.body:
        uses.extend(_node_uses(child, owner, bindings, known))
        if _callback_field(child, bindings, known):
            assert isinstance(child, ast.AnnAssign)
            assert isinstance(child.target, ast.Name)
            uses.append(_use(owner, child.target.id, child))
    return uses


def _callback_field(node: ast.stmt, bindings: dict[str, str], known: set[str]) -> bool:
    if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
        return False
    return _is_callback(node.annotation, bindings, known)


def _use(owner: str, name: str, node: ast.arg | ast.AnnAssign) -> CallbackUse:
    annotation = node.annotation
    assert annotation is not None
    return CallbackUse(owner, name, ast.unparse(annotation), node.lineno)


def _module_bindings(module: str, tree: ast.Module) -> dict[str, str]:
    bindings = _import_bindings(tree.body)
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            bindings[node.name] = f"{module}.{node.name}"
        if isinstance(node, ast.TypeAlias):
            bindings[node.name.id] = f"{module}.{node.name.id}"
        for name in _assignment_names(node):
            bindings[name] = f"{module}.{name}"
    return bindings


def _assignment_names(node: ast.stmt) -> list[str]:
    if not isinstance(node, ast.Assign):
        return []
    names = []
    for target in node.targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
    return names
