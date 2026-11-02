"""Resolve ordinary Python imports without executing the inspected modules."""

import ast
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path


@dataclass(frozen=True)
class ImportReference:
    """Identify an imported module or symbol at its original source location.

    Args:
        name: Absolute imported name, including a symbol when applicable.
        binding: Local name bound by the import statement.
        line: One-based source line for a useful assertion failure.
    """

    name: str
    binding: str
    line: int


def module_name(path: Path, root: Path) -> str:
    """Name a source module relative to the repository root.

    Args:
        path: Python module or package initializer.
        root: Repository root containing the package.

    Returns:
        Absolute import name, with package initializers normalized.
    """
    name = ".".join(path.relative_to(root).with_suffix("").parts)
    return name.removesuffix(".__init__")


def import_references(source: str, package: str) -> list[ImportReference]:
    """Resolve absolute, relative, aliased and type-only imports.

    Args:
        source: Module text to inspect without importing it.
        package: Absolute containing package for relative import resolution.

    Returns:
        Every static import, including those inside functions and TYPE_CHECKING.

    Raises:
        ImportError: A relative import escapes its containing package.
        SyntaxError: The inspected source is not valid Python.
    """
    references = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            references.extend(_absolute_imports(node))
        if isinstance(node, ast.ImportFrom):
            references.extend(_from_imports(node, package))
    return references


def _absolute_imports(node: ast.Import) -> list[ImportReference]:
    references = []
    for alias in node.names:
        binding = alias.asname or alias.name.split(".")[0]
        references.append(ImportReference(alias.name, binding, node.lineno))
    return references


def _from_imports(node: ast.ImportFrom, package: str) -> list[ImportReference]:
    owner = node.module or ""
    if node.level:
        owner = resolve_name("." * node.level + owner, package)
    references = []
    for alias in node.names:
        name = f"{owner}.{alias.name}"
        references.append(
            ImportReference(name, alias.asname or alias.name, node.lineno)
        )
    return references


def containing_module(name: str, modules: set[str]) -> str | None:
    """Find the longest actual module prefix of an imported symbol.

    Args:
        name: Absolute module or symbol reference.
        modules: Source module inventory.

    Returns:
        Matching module, or none for an external reference.
    """
    while name:
        if name in modules:
            return name
        name = name.rpartition(".")[0]
    return None


def dependency_graph(root: Path, layer: str) -> dict[str, set[str]]:
    """Build the complete static import graph for one business layer.

    Args:
        root: Repository root containing spotify_manager.
        layer: Domain or application package to inspect recursively.

    Returns:
        Module dependencies including relative, aliased and type-only imports.
    """
    paths = sorted((root / "spotify_manager" / layer).rglob("*.py"))
    modules = {module_name(path, root) for path in paths}
    graph = {}
    for path in paths:
        name = module_name(path, root)
        graph[name] = _dependencies(path, name, modules)
    return graph


def _dependencies(path: Path, name: str, modules: set[str]) -> set[str]:
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    dependencies = set()
    for reference in import_references(path.read_text(), package):
        target = containing_module(reference.name, modules)
        if target is not None and target != name:
            dependencies.add(target)
    return dependencies


def private_routine_references(source: str, module: str) -> list[str]:
    """Find private cross-routine imports and module-qualified references.

    Args:
        source: Production source text, including compatibility adapters.
        module: Absolute name of the inspected module.

    Returns:
        Prohibited imported names, resolving ordinary module aliases.
    """
    package = module.rpartition(".")[0]
    imports = import_references(source, package)
    bindings = _bindings(source, imports)
    references = {reference.name for reference in imports}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute):
            references.add(_qualified_name(node, bindings))
    return sorted(name for name in references if _private_routine(name, module))


def _bindings(source: str, imports: list[ImportReference]) -> dict[str, str]:
    bindings = {}
    for reference in imports:
        bindings[reference.binding] = reference.name
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            bindings.update(_absolute_bindings(node))
    return bindings


def _absolute_bindings(node: ast.Import) -> dict[str, str]:
    bindings = {}
    for alias in node.names:
        binding = alias.asname or alias.name.split(".")[0]
        bindings[binding] = alias.name if alias.asname else binding
    return bindings


def _qualified_name(node: ast.AST, bindings: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return bindings.get(node.id, "")
    if not isinstance(node, ast.Attribute):
        return ""
    owner = _qualified_name(node.value, bindings)
    return f"{owner}.{node.attr}" if owner else ""


def _private_routine(name: str, module: str) -> bool:
    parts = name.split(".")
    if len(parts) < 4 or parts[:2] != ["spotify_manager", "routines"]:
        return False
    if module == ".".join(parts[:3]):
        return False
    return parts[3].startswith("_")
