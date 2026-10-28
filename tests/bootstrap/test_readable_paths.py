"""Prevent the structural indirection rejected during Item 7a review."""

import ast
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[2] / "spotify_manager"
EXECUTION_METHODS = {"run", "execute", "review", "prepare", "finish", "refill", "plan"}


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _parameter_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    return len(node.args.posonlyargs + node.args.args + node.args.kwonlyargs)


def _constructor_fields(node: ast.ClassDef) -> list[ast.AnnAssign]:
    fields = []
    for declaration in node.body:
        if isinstance(declaration, ast.AnnAssign) and _constructor_input(declaration):
            fields.append(declaration)
    return fields


def _constructor_input(node: ast.AnnAssign) -> bool:
    if not isinstance(node.value, ast.Call):
        return True
    for keyword in node.value.keywords:
        if keyword.arg == "init" and isinstance(keyword.value, ast.Constant):
            return keyword.value.value is not False
    return True


def test_python_signatures_have_at_most_thirteen_parameters() -> None:
    """Enforce the owner-approved ceiling throughout the production package."""
    violations = []
    for path in PACKAGE.rglob("*.py"):
        violations.extend(_large_signatures(path))
    assert violations == []


def _large_signatures(path: Path) -> list[str]:
    violations = []
    for node in ast.walk(_module(path)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _parameter_count(node) > 13:
            violations.append(f"{path.name}:{node.name}")
    return violations


def test_delivery_and_request_constructors_are_small() -> None:
    """Prevent hiding large dependency lists in generated invocation constructors."""
    violations = []
    directories = (
        "interfaces/requests",
        "interfaces/http/workers",
        "interfaces/cli/features",
    )
    for directory in directories:
        violations.extend(_large_constructors(PACKAGE / directory))
    assert violations == []


def _large_constructors(directory: Path) -> list[str]:
    violations = []
    for path in directory.glob("*.py"):
        violations.extend(_class_violations(path))
    return violations


def _class_violations(path: Path) -> list[str]:
    violations = []
    for node in _module(path).body:
        if isinstance(node, ast.ClassDef) and len(_constructor_fields(node)) > 13:
            violations.append(f"{path.name}:{node.name}")
    return violations


def test_route_declarations_stay_beside_endpoint_definitions() -> None:
    """Keep URL-to-handler navigation in the API source without router factories."""
    from spotify_manager import api

    declarations = _route_names(_module(PACKAGE / "api.py"))
    endpoints = set()
    for route in api.app.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None and endpoint.__module__ == "spotify_manager.api":
            endpoints.add(endpoint.__name__)
    assert declarations == endpoints
    assert len(endpoints) == 115


def _route_names(module: ast.Module) -> set[str]:
    names = set()
    for node in module.body:
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and _has_route_declaration(node):
            names.add(node.name)
    return names


def _has_route_declaration(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if (
            isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "api_route"
        ):
            return True
    return False


def test_handlers_do_not_inject_forwarding_function_containers() -> None:
    """Require directly named feature handlers instead of Callable-only classes."""
    violations = []
    for path in (PACKAGE / "interfaces/http/handlers").glob("*.py"):
        violations.extend(_handler_containers(path))
    assert violations == []


def _handler_containers(path: Path) -> list[str]:
    violations = []
    for node in _module(path).body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not _is_protocol(node):
            violations.append(f"{path.name}:{node.name}")
    return violations


def _is_protocol(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True
    return False


def test_bootstrap_does_not_execute_application_stages() -> None:
    """Keep bootstrap construction separate from input acquisition and execution."""
    violations = []
    for path in (PACKAGE / "bootstrap").glob("*.py"):
        violations.extend(_execution_calls(path))
    assert violations == []


def _execution_calls(path: Path) -> list[str]:
    violations = []
    for node in ast.walk(_module(path)):
        if _is_asyncio_boundary(path, node):
            continue
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr in EXECUTION_METHODS:
            violations.append(f"{path.name}:{node.lineno}:{node.func.attr}")
    return violations


def test_lastfm_client_creation_has_one_concrete_owner() -> None:
    """Keep credentials and SDK construction outside legacy routine execution."""
    owners = []
    for path in PACKAGE.rglob("*.py"):
        if _constructs_lastfm(_module(path)):
            owners.append(path.relative_to(PACKAGE).as_posix())
    assert owners == ["bootstrap/clients.py"]


def _constructs_lastfm(module: ast.Module) -> bool:
    constructors = {"LastFmClient"}
    for node in module.body:
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "spotify_manager.client.lastfm"
        ):
            constructors.update(_client_aliases(node))
    for expression in ast.walk(module):
        if isinstance(expression, ast.Call) and isinstance(expression.func, ast.Name):
            if expression.func.id in constructors:
                return True
    return False


def _client_aliases(node: ast.ImportFrom) -> set[str]:
    names = set()
    for alias in node.names:
        if alias.name == "LastFmClient":
            names.add(alias.asname or alias.name)
    return names


def _is_asyncio_boundary(path: Path, node: ast.AST) -> bool:
    if path.name != "execution.py" or not isinstance(node, ast.Call):
        return False
    if ast.unparse(node.func) != "asyncio.run":
        return False
    for function in _module(path).body:
        if not isinstance(function, ast.FunctionDef):
            continue
        if (
            function.name in {"run_cli", "run_python"}
            and node.lineno >= function.lineno
            and node.end_lineno <= function.end_lineno
        ):
            return True
    return False


def test_synchronous_locks_never_span_an_await() -> None:
    """Keep contended threading locks from stopping the web event loop."""
    violations = []
    for path in PACKAGE.rglob("*.py"):
        violations.extend(_awaiting_thread_locks(path))
    assert violations == []


def _awaiting_thread_locks(path: Path) -> list[str]:
    violations = []
    for node in ast.walk(_module(path)):
        if not isinstance(node, ast.With):
            continue
        if _names_a_lock(node) and _contains_await(node):
            violations.append(f"{path.name}:{node.lineno}")
    return violations


def _names_a_lock(node: ast.With) -> bool:
    for item in node.items:
        name = ast.unparse(item.context_expr)
        if name == "lock" or name.endswith(("_lock", ".lock")):
            return True
    return False


def _contains_await(node: ast.With) -> bool:
    return any(isinstance(child, ast.Await) for child in ast.walk(node))
