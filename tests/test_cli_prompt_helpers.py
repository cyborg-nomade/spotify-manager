"""Focused tests for interactive CLI choices and compact renderers."""

from io import StringIO
from types import SimpleNamespace

import pytest
from rich.console import Console

from spotify_manager import main


class Pausable:
    """Record the lifecycle calls made around an interactive prompt."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def stop(self) -> None:
        self.calls.append("stop")

    def start(self) -> None:
        self.calls.append("start")


def _console() -> Console:
    return Console(file=StringIO(), width=160)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("1", "track-1"),
        ("s", main.artist_review.CHOICE_SKIP),
        ("q", main.artist_review.CHOICE_QUIT),
    ],
)
def test_artist_track_prompt_maps_every_action(
    monkeypatch: pytest.MonkeyPatch,
    response: str,
    expected: str,
) -> None:
    progress = Pausable()
    candidate = SimpleNamespace(
        spotify_id="track-1",
        name="Track",
        album="Album",
        primary_artist_name="Artist",
        rank=1,
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: response)

    choice = main.ask_artist_track_choice(
        _console(),
        SimpleNamespace(name="Artist"),
        (candidate,),  # type: ignore[arg-type]
        progress,  # type: ignore[arg-type]
    )

    assert choice == expected
    assert progress.calls == ["stop", "start"]


@pytest.mark.parametrize(
    ("responses", "expected"),
    [
        (["n"], main.artist_review.CHOICE_DECLINE),
        (["s"], main.artist_review.CHOICE_SKIP),
        (["q"], main.artist_review.CHOICE_QUIT),
        (["y", "1"], "release-1"),
    ],
)
def test_artist_release_prompt_maps_decline_and_selection(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[str],
    expected: str,
) -> None:
    answers = iter(responses)
    candidate = SimpleNamespace(
        spotify_id="release-1",
        name="Album",
        release_type="Album",
        release_date="2020-01-01",
        first_track_name="Opening",
        first_track_primary_artist_name="Artist",
        is_eligible_for=lambda artist_id: artist_id == "artist-1",
    )
    monkeypatch.setattr(
        main.Prompt,
        "ask",
        lambda *_args, **_kwargs: next(answers),
    )

    choice = main.ask_artist_release_choice(
        _console(),
        SimpleNamespace(name="Artist", spotify_id="artist-1"),
        (candidate,),  # type: ignore[arg-type]
        allow_decline=True,
    )

    assert choice == expected


def test_artist_release_prompt_marks_ineligible_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = SimpleNamespace(
        spotify_id="release-1",
        name="Album",
        release_type="Album",
        release_date="2020",
        first_track_name=None,
        first_track_primary_artist_name=None,
        is_eligible_for=lambda _artist_id: False,
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: "s")

    assert (
        main.ask_artist_release_choice(
            _console(),
            SimpleNamespace(name="Artist", spotify_id="artist-1"),
            (candidate,),  # type: ignore[arg-type]
            allow_decline=False,
        )
        == main.artist_review.CHOICE_SKIP
    )


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("1", "release-1"),
        ("s", main.new_wine.CHOICE_SKIP),
        ("q", main.new_wine.CHOICE_QUIT),
    ],
)
def test_new_wine_prompt_maps_common_actions(
    monkeypatch: pytest.MonkeyPatch,
    response: str,
    expected: str,
) -> None:
    candidate = SimpleNamespace(
        spotify_id="release-1",
        name="Album",
        release_type="Album",
        release_date="2020",
        total_tracks=10,
        primary_artist_name="Artist",
    )
    source = SimpleNamespace(
        primary_artist_name="Artist",
        name="Current",
        release=SimpleNamespace(release_type="Album"),
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: response)

    assert (
        main.ask_new_wine_release_choice(
            _console(),
            source,  # type: ignore[arg-type]
            (candidate,),  # type: ignore[arg-type]
        )
        == expected
    )


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("1", "release-1"),
        ("s", main.new_kids.CHOICE_SKIP),
        ("q", main.new_kids.CHOICE_QUIT),
    ],
)
def test_new_kids_prompt_maps_every_action(
    monkeypatch: pytest.MonkeyPatch,
    response: str,
    expected: str,
) -> None:
    candidate = SimpleNamespace(
        spotify_id="release-1",
        name="Album",
        release_type="Album",
        release_date="2020",
        total_tracks=10,
        popularity=None,
        top_track_rank=None,
        saved=False,
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: response)

    assert (
        main.ask_new_kids_release_choice(
            _console(),
            "Artist",
            (candidate,),  # type: ignore[arg-type]
        )
        == expected
    )


def test_album_discovery_renderer_handles_empty_and_detailed_rows() -> None:
    console = _console()
    main.print_album_discovery_decisions(console, "Decisions", ())
    main.print_album_discovery_decisions(
        console,
        "Decisions",
        (
            SimpleNamespace(
                artist="Artist",
                source_track="Current",
                source_release="Old",
                current_liked=True,
                consecutive_unliked=0,
                action="next release",
                target_track="Opening",
                target_release="New",
            ),
        ),  # type: ignore[arg-type]
    )

    output = console.file.getvalue()  # type: ignore[union-attr]
    assert "Artist" in output
    assert "New - Opening" in output


def test_slow_listening_order_reprompts_until_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = tuple(
        SimpleNamespace(
            spotify_id=f"release-{number}",
            name=f"Album {number}",
            release_type="Album",
            total_tracks=10,
            plain=number == 1,
            saved=number == 2,
        )
        for number in (1, 2)
    )
    responses = iter(["bad", "1,1", "2,1"])
    monkeypatch.setattr(
        main.Prompt,
        "ask",
        lambda *_args, **_kwargs: next(responses),
    )

    assert main.ask_slow_listening_release_order(
        _console(),
        "2020-01-01",
        candidates,  # type: ignore[arg-type]
    ) == ("release-2", "release-1")


def test_slow_listening_order_can_quit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: "q")
    with pytest.raises(main.slow_listening.SlowListeningCancelledError):
        main.ask_slow_listening_release_order(
            _console(),
            "2020",
            (
                SimpleNamespace(
                    name="A",
                    release_type="Album",
                    total_tracks=1,
                    plain=True,
                    saved=True,
                ),
            ),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("a", main.slow_listening.CHOICE_ADVANCE),
        ("s", main.slow_listening.CHOICE_SKIP),
        ("q", main.slow_listening.CHOICE_QUIT),
    ],
)
def test_slow_listening_action_maps_every_choice(
    monkeypatch: pytest.MonkeyPatch,
    response: str,
    expected: str,
) -> None:
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: response)
    assert (
        main.ask_slow_listening_action(
            _console(),
            SimpleNamespace(primary_artist_name="Artist", name="Current"),  # type: ignore[arg-type]
            SimpleNamespace(name="Next"),  # type: ignore[arg-type]
            SimpleNamespace(name="Album"),  # type: ignore[arg-type]
        )
        == expected
    )


@pytest.mark.parametrize(
    ("response", "expected"),
    [("y", main.queue_3.CHOICE_ADVANCE), ("q", main.queue_3.CHOICE_QUIT)],
)
def test_queue_3_release_transition_maps_actions(
    monkeypatch: pytest.MonkeyPatch,
    response: str,
    expected: str,
) -> None:
    release = SimpleNamespace(
        name="Album",
        release_type="Album",
        chronology_date="2020",
        total_tracks=10,
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: response)

    assert (
        main.ask_queue_3_release_transition(
            _console(),
            SimpleNamespace(primary_artist_name="Artist"),  # type: ignore[arg-type]
            release,  # type: ignore[arg-type]
            release,  # type: ignore[arg-type]
        )
        == expected
    )


@pytest.mark.parametrize(
    ("response", "expected"),
    [("1", "playlist-1"), ("q", main.queue_3.CHOICE_QUIT)],
)
def test_queue_3_composer_prompt_maps_actions(
    monkeypatch: pytest.MonkeyPatch,
    response: str,
    expected: str,
) -> None:
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: response)
    assert (
        main.ask_queue_3_composer_playlist(
            _console(),
            "Composer",
            (SimpleNamespace(spotify_id="playlist-1", name="Works", total_tracks=5),),  # type: ignore[arg-type]
        )
        == expected
    )


def test_discography_selection_reprompts_then_parses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = SimpleNamespace(
        spotify_id="release-1",
        name="Album",
        release_type="Album",
        chronology_date="2020",
        total_tracks=10,
        saved=True,
        default=True,
    )
    responses = iter(["bad", "1"])
    monkeypatch.setattr(
        main.Prompt,
        "ask",
        lambda *_args, **_kwargs: next(responses),
    )

    assert main.ask_discography_release_selection(
        _console(),
        SimpleNamespace(name="Artist"),  # type: ignore[arg-type]
        (release,),  # type: ignore[arg-type]
    ) == ("release-1",)


@pytest.mark.parametrize("response", ["n", "q"])
def test_discography_selection_can_clear_or_quit(
    monkeypatch: pytest.MonkeyPatch,
    response: str,
) -> None:
    release = SimpleNamespace(
        spotify_id="release-1",
        name="Album",
        release_type="Album",
        chronology_date="2020",
        total_tracks=10,
        saved=False,
        default=False,
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: response)

    if response == "q":
        with pytest.raises(main.discography.DiscographyCancelledError):
            main.ask_discography_release_selection(
                _console(),
                SimpleNamespace(name="Artist"),  # type: ignore[arg-type]
                (release,),  # type: ignore[arg-type]
            )
    else:
        assert (
            main.ask_discography_release_selection(
                _console(),
                SimpleNamespace(name="Artist"),  # type: ignore[arg-type]
                (release,),  # type: ignore[arg-type]
            )
            == ()
        )


def test_slow_listening_completion_pauses_for_user() -> None:
    progress = Pausable()
    calls: list[str] = []
    console = SimpleNamespace(
        print=lambda *_args, **_kwargs: calls.append("print"),
        input=lambda *_args, **_kwargs: calls.append("input"),
    )

    main.acknowledge_slow_listening_completion(
        console,  # type: ignore[arg-type]
        SimpleNamespace(primary_artist_name="Artist"),  # type: ignore[arg-type]
        progress,  # type: ignore[arg-type]
    )

    assert calls == ["print", "input"]
    assert progress.calls == ["stop", "start"]


@pytest.mark.parametrize(
    ("response", "expected"),
    [("1", "artist-1"), ("q", "quit")],
)
def test_something_old_artist_prompt_maps_selection_and_quit(
    monkeypatch: pytest.MonkeyPatch,
    response: str,
    expected: str,
) -> None:
    status = Pausable()
    candidates = (
        SimpleNamespace(
            spotify_id="artist-1",
            name="Artist",
            popularity=80,
            followers=1_000,
        ),
        SimpleNamespace(
            spotify_id="artist-2",
            name="Artist",
            popularity=None,
            followers=None,
        ),
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: response)

    assert (
        main.ask_something_old_artist(
            _console(),
            "Artist",
            candidates,  # type: ignore[arg-type]
            status,  # type: ignore[arg-type]
        )
        == expected
    )
    assert status.calls == ["stop", "start"]


@pytest.mark.parametrize(
    ("responses", "expected"),
    [
        (["1"], "artist-1"),
        (["s"], main.release_check.CHOICE_SKIP),
        (["p"], main.release_check.CHOICE_SKIP_ARTIST),
        (["q"], main.release_check.CHOICE_QUIT),
        (
            ["n", "", "New Search"],
            f"{main.release_check.CHOICE_SEARCH_PREFIX}New Search",
        ),
    ],
)
def test_release_check_artist_prompt_maps_all_actions(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[str],
    expected: str,
) -> None:
    progress = Pausable()
    answers = iter(responses)
    monkeypatch.setattr(
        main.Prompt,
        "ask",
        lambda *_args, **_kwargs: next(answers),
    )
    candidate = SimpleNamespace(
        spotify_id="artist-1",
        name="Artist",
        exact_name=False,
        popularity=None,
        followers=None,
    )

    assert (
        main.ask_release_check_artist(
            _console(),
            SimpleNamespace(rank=1, name="Artist", scrobbles=100),  # type: ignore[arg-type]
            (candidate,),  # type: ignore[arg-type]
            progress,  # type: ignore[arg-type]
        )
        == expected
    )
    assert progress.calls == ["stop", "start"]


def test_release_check_artist_prompt_handles_no_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    progress = Pausable()
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: "s")
    assert (
        main.ask_release_check_artist(
            _console(),
            SimpleNamespace(rank=1, name="Missing", scrobbles=100),  # type: ignore[arg-type]
            (),
            progress,  # type: ignore[arg-type]
        )
        == main.release_check.CHOICE_SKIP
    )


@pytest.mark.parametrize(
    ("responses", "expected"),
    [
        (["1"], "artist-1"),
        (["s"], main.the_queue.CHOICE_SKIP),
        (["q"], main.the_queue.CHOICE_QUIT),
        (
            ["n", "", "Alternate Artist"],
            f"{main.the_queue.CHOICE_SEARCH_PREFIX}Alternate Artist",
        ),
    ],
)
def test_queue_artist_prompt_maps_all_actions(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[str],
    expected: str,
) -> None:
    progress = Pausable()
    answers = iter(responses)
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: next(answers))
    candidates = (
        SimpleNamespace(
            spotify_id="artist-1",
            name="Exact Artist",
            exact_name=True,
            popularity=80,
            followers=1_000,
        ),
        SimpleNamespace(
            spotify_id="artist-2",
            name="Possible Artist",
            exact_name=False,
            popularity=None,
            followers=None,
        ),
    )

    assert (
        main.ask_queue_artist(
            _console(),
            SimpleNamespace(artist="Last.fm Artist"),  # type: ignore[arg-type]
            candidates,  # type: ignore[arg-type]
            progress,  # type: ignore[arg-type]
        )
        == expected
    )
    assert progress.calls == ["stop", "start"]


def test_queue_artist_prompt_handles_no_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    progress = Pausable()
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: "s")

    assert (
        main.ask_queue_artist(
            _console(),
            SimpleNamespace(artist="Missing"),  # type: ignore[arg-type]
            (),
            progress,  # type: ignore[arg-type]
        )
        == main.the_queue.CHOICE_SKIP
    )
    assert progress.calls == ["stop", "start"]


@pytest.mark.parametrize(
    ("response", "expected"),
    [("1", "release-1"), ("q", "quit")],
)
def test_something_old_album_prompt_maps_selection_and_quit(
    monkeypatch: pytest.MonkeyPatch,
    response: str,
    expected: str,
) -> None:
    status = Pausable()
    releases = (
        SimpleNamespace(
            spotify_id="release-1",
            chronology_date="2020-01-01",
            release_type="Album",
            name="Album",
            total_tracks=10,
            saved=True,
            plain=False,
        ),
        SimpleNamespace(
            spotify_id="release-2",
            chronology_date="2021-01-01",
            release_type="EP",
            name="EP",
            total_tracks=4,
            saved=False,
            plain=True,
        ),
        SimpleNamespace(
            spotify_id="release-3",
            chronology_date="2022-01-01",
            release_type="Album",
            name="Deluxe",
            total_tracks=12,
            saved=False,
            plain=False,
        ),
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: response)

    assert (
        main.ask_something_old_album(
            _console(),
            SimpleNamespace(artist="Artist"),  # type: ignore[arg-type]
            releases,  # type: ignore[arg-type]
            status,  # type: ignore[arg-type]
        )
        == expected
    )
    assert status.calls == ["stop", "start"]
