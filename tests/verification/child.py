"""Run existing pure policy assertions inside a disposable source checkout."""

import sys
from pathlib import Path

from tests.verification.network import install_network_guard


def main() -> int:
    """Check the disposable import location before running unmodified policy tests.

    Returns:
        The original pytest process result.

    Raises:
        AssertionError: Imports escaped the disposable checkout.
    """
    sys.dont_write_bytecode = True
    install_network_guard()
    import pytest

    from spotify_manager import domain

    assert domain.__file__ is not None
    assert Path(domain.__file__).resolve().is_relative_to(Path.cwd())
    return int(pytest.main(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
