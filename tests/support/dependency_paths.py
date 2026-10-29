"""Inspect concrete invocation bindings without importing SDK or startup modules."""

import ast
from pathlib import Path


Bindings = dict[str, str]
EXECUTION_LAYERS = (
    "spotify_manager.bootstrap.",
    "spotify_manager.interfaces.operations.",
    "spotify_manager.interfaces.lookup_operations.",
    "spotify_manager.interfaces.sauvignon_operations.",
)


def _import_bindings(nodes: list[ast.stmt]) -> Bindings:
    bindings: Bindings = {}
    for node in nodes:
        _bind_import(node, bindings)
    return bindings


def _bind_import(node: ast.AST, bindings: Bindings) -> None:
    if isinstance(node, ast.ImportFrom):
        for alias in node.names:
            bindings[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    if isinstance(node, ast.Import):
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            bindings[name] = alias.name if alias.asname else name


def _target(node: ast.AST, bindings: Bindings) -> str:
    if isinstance(node, ast.Name):
        return bindings.get(node.id, "")
    if not isinstance(node, ast.Attribute):
        return ""
    owner = _target(node.value, bindings)
    return f"{owner}.{node.attr}" if owner else ""


def _function_bindings(
    function: ast.FunctionDef | ast.AsyncFunctionDef, outer: Bindings
) -> Bindings:
    bindings = dict(outer)
    for argument in ast.walk(function.args):
        if isinstance(argument, ast.arg):
            bindings.pop(argument.arg, None)
    for node in ast.walk(function):
        _bind_import(node, bindings)
    return bindings


def forwarding_functions(source: str, module: str) -> set[str]:
    """Identify legacy functions that invoke composition or shared operations.

    Args:
        source: Python module text to inspect without importing it.
        module: Fully qualified name of that legacy module.

    Returns:
        Qualified forwarding-function names, excluding callable parameters.
    """
    tree = ast.parse(source)
    outer = _import_bindings(tree.body)
    result: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _forwards(
            node, outer
        ):
            result.add(f"{module}.{node.name}")
    return result


def _forwards(
    function: ast.FunctionDef | ast.AsyncFunctionDef, outer: Bindings
) -> bool:
    bindings = _function_bindings(function, outer)
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if _target(node.func, bindings).startswith(EXECUTION_LAYERS):
            return True
    return False


def facade_forwarders(root: Path) -> set[str]:
    """Inventory execution facades from their actual function implementations.

    Args:
        root: Repository root containing the production package.

    Returns:
        Names of routine and processor functions that forward execution inward.
    """
    result: set[str] = set()
    for directory in ("routines", "processors"):
        result.update(_directory_forwarders(root, directory))
    return result


def _directory_forwarders(root: Path, directory: str) -> set[str]:
    result: set[str] = set()
    for path in (root / "spotify_manager" / directory).glob("*.py"):
        module = f"spotify_manager.{directory}.{path.stem}"
        result.update(forwarding_functions(path.read_text(), module))
    return result


def forwarding_references(source: str, prohibited: set[str]) -> list[str]:
    """Find imports and module-qualified references to execution facades.

    Args:
        source: Production module text to inspect.
        prohibited: Qualified legacy forwarding-function names.

    Returns:
        Source locations of bindings that could reintroduce a facade detour.
    """
    tree = ast.parse(source)
    bindings: Bindings = {}
    for node in ast.walk(tree):
        _bind_import(node, bindings)
    result: list[str] = []
    for node in ast.walk(tree):
        result.extend(_reference(node, bindings, prohibited))
    return result


def _reference(node: ast.AST, bindings: Bindings, prohibited: set[str]) -> list[str]:
    target = _target(node, bindings)
    if isinstance(node, (ast.Name, ast.Attribute)) and target in prohibited:
        return [f"{node.lineno}: {target}"]
    if not isinstance(node, ast.ImportFrom):
        return []
    references = []
    for alias in node.names:
        target = f"{node.module}.{alias.name}"
        if target in prohibited:
            references.append(f"{node.lineno}: {target}")
    return references


def _module_name(root: Path, path: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def legacy_callable_names(root: Path) -> set[str]:
    """Inventory concrete functions exported by routine and processor namespaces.

    Args:
        root: Repository root containing all explicit implementation owners.

    Returns:
        Qualified concrete and re-exported legacy function names.
    """
    functions: set[str] = set()
    aliases: dict[str, str] = {}
    for path in (root / "spotify_manager").rglob("*.py"):
        _module_callables(root, path, functions, aliases)
    _resolve_aliases(functions, aliases)
    return _legacy_names(functions)


def _module_callables(
    root: Path, path: Path, functions: set[str], aliases: dict[str, str]
) -> None:
    module = _module_name(root, path)
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.FunctionDef):
            functions.add(f"{module}.{node.name}")
        if isinstance(node, ast.ImportFrom):
            _module_aliases(module, node, aliases)


def _module_aliases(module: str, node: ast.ImportFrom, aliases: dict[str, str]) -> None:
    for alias in node.names:
        aliases[f"{module}.{alias.asname or alias.name}"] = (
            f"{node.module}.{alias.name}"
        )


def _resolve_aliases(functions: set[str], aliases: dict[str, str]) -> None:
    pending = dict(aliases)
    while pending:
        matched = _matched_aliases(pending, functions)
        if not matched:
            return
        functions.update(matched)
        for alias in matched:
            del pending[alias]


def _legacy_names(functions: set[str]) -> set[str]:
    names: set[str] = set()
    for name in functions:
        if name.startswith(
            ("spotify_manager.routines.", "spotify_manager.processors.")
        ):
            names.add(name)
    return names


def dynamic_facade_bindings(source: str, callables: set[str]) -> list[str]:
    """Reject function lookup through mutable facade-module globals.

    Args:
        source: A concrete composition or infrastructure implementation.
        callables: Concrete and re-exported legacy function names.

    Returns:
        Locations of dynamic module attributes instead of explicit imports.
    """
    tree = ast.parse(source)
    bindings: Bindings = {}
    for node in ast.walk(tree):
        _bind_import(node, bindings)
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        target = _target(node, bindings)
        if target in callables:
            result.append(f"{node.lineno}: {target}")
    return result


def _matched_aliases(aliases: dict[str, str], functions: set[str]) -> list[str]:
    matched = []
    for alias, target in aliases.items():
        if target in functions:
            matched.append(alias)
    return matched


def injected_policies(source: str, policies: set[str]) -> list[str]:
    """Find fixed domain functions supplied as executable dependencies.

    Args:
        source: Python source inspected without importing the application.
        policies: Qualified domain functions that must be called directly.

    Returns:
        Original line numbers and qualified injected functions.
    """
    tree = ast.parse(source)
    outer = _import_bindings(tree.body)
    result = []
    for node in tree.body:
        result.extend(_node_policies(node, outer, policies))
    return sorted(set(result))


def _node_policies(node: ast.AST, outer: Bindings, policies: set[str]) -> list[str]:
    if isinstance(node, ast.FunctionDef):
        return _policy_arguments(node, _function_bindings(node, outer), policies)
    if not isinstance(node, ast.ClassDef):
        return _policy_arguments(node, outer, policies)
    result = []
    for child in node.body:
        result.extend(_node_policies(child, outer, policies))
    return result


def _policy_arguments(
    tree: ast.AST, bindings: Bindings, policies: set[str]
) -> list[str]:
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _collection_operation(node):
            continue
        result.extend(_call_policies(node, bindings, policies))
    return result


def _call_policies(call: ast.Call, bindings: Bindings, policies: set[str]) -> list[str]:
    arguments = [*call.args, *(item.value for item in call.keywords)]
    result = []
    for argument in arguments:
        target = _target(argument, bindings)
        if target in policies:
            result.append(f"{argument.lineno}: {target}")
    return result


def _collection_operation(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Name) and node.func.id in {
        "sorted",
        "min",
        "max",
        "map",
        "filter",
    }


def domain_functions(root: Path) -> set[str]:
    """Inventory fixed domain functions without importing configuration or clients.

    Args:
        root: Repository root containing the production domain package.

    Returns:
        Qualified module-level domain functions, excluding data constructors.
    """
    result = set()
    for path in (root / "spotify_manager/domain").rglob("*.py"):
        result.update(_module_functions(path, root))
    return result


def _module_functions(path: Path, root: Path) -> set[str]:
    module = ".".join(path.relative_to(root).with_suffix("").parts)
    result = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.FunctionDef):
            result.add(f"{module}.{node.name}")
    return result
