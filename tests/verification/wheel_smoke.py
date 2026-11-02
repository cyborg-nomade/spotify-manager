"""Verify a locally built wheel with synthetic configuration and no live services."""

import argparse
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _environment(temporary: Path) -> dict[str, str]:
    return {
        "PATH": os.defpath,
        "SPOTIPY_CLIENT_ID": "wheel-client",
        "SPOTIPY_CLIENT_SECRET": "wheel-secret",
        "SPOTIPY_REDIRECT_URI": "http://127.0.0.1:8080/callback",
        "ALBUMS_TO_ADD": "10",
        "LIMIT": "50",
        "LASTFM_API_KEY": "wheel-lastfm",
        "LASTFM_USERNAME": "wheel-listener",
        "APP_PASSWORD": "wheel-password",
        "SPOTIFY_MANAGER_STATE_BACKEND": "local",
        "SPOTIFY_MANAGER_STATE_LOCAL_PATH": str(temporary / "state.json"),
        "SPOTIFY_MANAGER_DATA_BACKEND": "local",
        "SPOTIFY_MANAGER_DATA_LOCAL_ROOT": str(temporary / "data"),
        "HF_HOME": str(temporary / "hf"),
        "NO_COLOR": "1",
        "TERM": "dumb",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _verify_sources(site: Path) -> None:
    paths = list((ROOT / "spotify_manager").rglob("*.py"))
    paths.extend((ROOT / "spotify_manager/frontend").glob("*.html"))
    for path in paths:
        packaged = site / path.relative_to(ROOT)
        assert packaged.read_bytes() == path.read_bytes(), path.relative_to(ROOT)
    print(f"Verified {len(paths)} packaged Python/frontend files against checkout.")


def verify_wheel(wheel: Path) -> None:
    """Check packaged bytes and execute only offline entry-point inspection.

    Args:
        wheel: Locally built, trusted project wheel.

    Raises:
        AssertionError: Packaged sources, imports or entry-point contracts differ.
        OSError: A package file or child process is unavailable.
        subprocess.TimeoutExpired: The bounded smoke process fails to finish.
    """
    with tempfile.TemporaryDirectory(prefix="spotify-wheel-") as directory:
        temporary = Path(directory)
        site = temporary / "site"
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(site)
        _verify_sources(site)
        command = [
            sys.executable,
            str(Path(__file__).with_name("wheel_child.py")),
            str(site),
            str(ROOT),
        ]
        completed = subprocess.run(
            command,
            cwd=temporary,
            env=_environment(temporary),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        print(completed.stdout.strip())


def main() -> None:
    """Read the explicit wheel argument and verify that artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    arguments = parser.parse_args()
    verify_wheel(arguments.wheel)


if __name__ == "__main__":
    main()
