"""Tests for review-album-limits CLI prompting."""

from types import SimpleNamespace

from rich.console import Console

from spotify_manager import main


class FakeProgress:
    """Small progress stand-in recording start/stop calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def stop(self) -> None:
        self.calls.append("stop")

    def start(self) -> None:
        self.calls.append("start")


def test_ask_review_action_pauses_progress_while_prompting(monkeypatch) -> None:
    progress = FakeProgress()
    prompt_call: dict[str, object] = {}

    def fake_ask(
        prompt: str,
        choices: list[str],
        default: str,
        console: Console,
    ) -> str:
        prompt_call.update(
            {
                "prompt": prompt,
                "choices": choices,
                "default": default,
                "console": console,
            }
        )
        return "r"

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)
    console = Console()

    result = main.ask_review_action(
        console,
        SimpleNamespace(decision="remove"),
        progress,
    )

    assert result == "r"
    assert progress.calls == ["stop", "start"]
    assert prompt_call["default"] == "r"
    assert prompt_call["console"] is console


def test_ask_review_action_defaults_to_skip_for_non_remove(monkeypatch) -> None:
    prompt_call: dict[str, object] = {}

    def fake_ask(
        prompt: str,
        choices: list[str],
        default: str,
        console: Console,
    ) -> str:
        prompt_call["default"] = default
        return "s"

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)

    result = main.ask_review_action(Console(), SimpleNamespace(decision="keep"))

    assert result == "s"
    assert prompt_call["default"] == "s"


def test_review_client_disables_spotipy_retries(monkeypatch) -> None:
    calls: list[dict[str, int]] = []
    fake_client = object()
    monkeypatch.setattr(main, "_review_client", None)

    def fake_get_spotipy_client(**kwargs):
        calls.append(kwargs)
        return fake_client

    monkeypatch.setattr(main, "get_spotipy_client", fake_get_spotipy_client)

    assert main.review_client() is fake_client
    assert main.review_client() is fake_client
    assert calls == [{"retries": 0, "status_retries": 0}]
