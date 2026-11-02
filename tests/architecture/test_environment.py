"""Keep machine-specific terminal settings out of offline behavioral assertions."""

import os
from pathlib import Path

import pytest

from tests.support.isolation import TERMINAL_VARIABLES
from tests.support.isolation import isolate_environment


def test_isolation_removes_ci_color_forcing_before_application_imports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reproduce GitHub's terminal detection without altering application rendering.

    Args:
        monkeypatch: Scope synthetic CI/color flags to this test.
        tmp_path: Disposable settings and cache root.
    """
    for name in TERMINAL_VARIABLES:
        monkeypatch.setenv(name, "1")
    with pytest.MonkeyPatch.context() as isolated:
        isolate_environment(isolated, tmp_path)
        for name in TERMINAL_VARIABLES:
            assert name not in os.environ
        assert os.environ["NO_COLOR"] == "1"
        assert os.environ["TERM"] == "dumb"
