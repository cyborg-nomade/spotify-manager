"""Apply a small explicit defect catalog only to disposable domain source copies."""

import ast
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[2]
POLICY_TESTS = (
    "test_album_and_artist_rules.py",
    "test_progression.py",
    "test_releases.py",
)


@dataclass(frozen=True)
class Mutation:
    """Describe one deliberate policy defect whose tests must reject it.

    Args:
        name: Readable defect identity in pytest reports.
        module: Domain source filename.
        before: Unique reviewed source fragment.
        after: Syntactically valid deliberate defect.
    """

    name: str
    module: str
    before: str
    after: str

    def apply(self, checkout: Path) -> None:
        """Alter only a copied module, rejecting stale or invalid mutation definitions.

        Args:
            checkout: Disposable copy of the selected domain code and tests.

        Raises:
            AssertionError: The original fragment is no longer unique.
            SyntaxError: The mutation would test a syntax error rather than a rule.
        """
        path = checkout / "spotify_manager/domain" / self.module
        source = path.read_text()
        assert source.count(self.before) == 1, self.name
        mutated = source.replace(self.before, self.after, 1)
        ast.parse(mutated)
        path.write_text(mutated)


MUTATIONS = (
    Mutation(
        "retention-floor",
        "albums.py",
        "floor(total_tracks * threshold)",
        "round(total_tracks * threshold)",
    ),
    Mutation(
        "retention-boundary",
        "albums.py",
        "liked_tracks >= required",
        "liked_tracks > required",
    ),
    Mutation(
        "liked-promotion",
        "artists.py",
        "facts.liked_tracks >= 18",
        "facts.liked_tracks > 18",
    ),
    Mutation(
        "saved-promotion",
        "artists.py",
        "facts.saved_releases >= 3",
        "facts.saved_releases > 3",
    ),
    Mutation(
        "liked-completeness",
        "completion.py",
        "liked_names <= matched_names",
        "liked_names >= matched_names",
    ),
    Mutation(
        "primary-credit",
        "progression.py",
        "track.primary_artist_id == artist_id",
        "track.primary_artist_id != artist_id",
    ),
    Mutation(
        "successor-order",
        "progression.py",
        "tracks[source_index + 1 :]",
        "tracks[source_index :]",
    ),
    Mutation(
        "saved-edition-priority", "releases.py", "        not saved,", "        saved,"
    ),
    Mutation(
        "partial-date-order",
        "releases.py",
        "month = parts[1] if len(parts) > 1 else 1",
        "month = parts[1] if len(parts) > 1 else 12",
    ),
)


@dataclass(frozen=True)
class Trial:
    """Retain execution and assertion evidence without counting collection failures.

    Args:
        status: Child pytest exit status.
        tests: Collected and executed test count.
        failures: Test-body failures.
        errors: Collection or setup errors.
        assertions: Failures with an actual assertion diagnostic.
    """

    status: int
    tests: int
    failures: int
    errors: int
    assertions: int

    @property
    def killed(self) -> bool:
        """Require normal pytest failure and genuine failed assertions.

        Returns:
            Whether this run establishes rejection of the deliberate defect.
        """
        return (
            self.status == 1
            and self.tests > 0
            and self.failures > 0
            and self.errors == 0
            and self.assertions > 0
        )


def copy_policy_checkout(destination: Path, source: Path = ROOT) -> None:
    """Copy Python policy sources and unchanged assertions without operator data.

    Args:
        destination: Disposable checkout directory.
        source: Reviewed source tree or a previously verified control copy.

    Raises:
        OSError: A source or temporary destination cannot be read or written.
    """
    paths = list((source / "spotify_manager/domain").rglob("*.py"))
    paths.append(source / "spotify_manager/__init__.py")
    for filename in POLICY_TESTS:
        paths.append(source / "tests/domain" / filename)
    for filename in ("__init__.py", "network.py", "child.py"):
        paths.append(source / "tests/verification" / filename)
    paths.append(source / "tests/__init__.py")
    for path in paths:
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def _child_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in tuple(environment):
        if name.startswith(("COV_CORE_", "COVERAGE_", "COV_")):
            del environment[name]
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def run_policy_tests(checkout: Path) -> Trial:
    """Run the same existing assertions with subprocess coverage kept separate.

    Args:
        checkout: Disposable, network-blocked source tree.

    Returns:
        Actual pytest and JUnit evidence; invalid launches never become kills.

    Raises:
        subprocess.TimeoutExpired: The bounded verification process fails to finish.
        OSError: The child process or its report is unavailable.
    """
    report = checkout / "trial.xml"
    report.unlink(missing_ok=True)
    command = [sys.executable, "-m", "tests.verification.child"]
    command.extend(["--confcutdir=tests/domain", "--junitxml=trial.xml", "-q"])
    for filename in POLICY_TESTS:
        command.append("tests/domain/" + filename)
    completed = subprocess.run(
        command,
        cwd=checkout,
        env=_child_environment(),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return read_trial(report, completed.returncode)


def read_trial(path: Path, status: int) -> Trial:
    """Read counters and assertion diagnostics from the child-owned JUnit report.

    Args:
        path: Report created by this exact invocation.
        status: Original process exit status.

    Returns:
        Complete evidence, including errors that invalidate mutation conclusions.

    Raises:
        OSError: The exact child report cannot be read.
        ElementTree.ParseError: The child produced an invalid XML report.
        ValueError: A report counter is not an integer.
    """
    report = ElementTree.parse(path).getroot()
    tests = failures = errors = assertions = 0
    for suite in report.findall("testsuite"):
        tests += int(suite.get("tests", "0"))
        failures += int(suite.get("failures", "0"))
        errors += int(suite.get("errors", "0"))
    for failure in report.findall(".//failure"):
        assertions += "assert " in failure.get("message", "")
    return Trial(status, tests, failures, errors, assertions)
