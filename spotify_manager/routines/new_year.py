"""Build a previous-year retrospective with durable, idempotent checkpoints."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime
from functools import partial
from typing import Any
from zoneinfo import ZoneInfo

from spotipy import Spotify

from spotify_manager.core.state.runtime import get_state_service
from spotify_manager.core.state.service import StateService
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import new_wine
from spotify_manager.routines import palace_of_memory
from spotify_manager.routines import queue_3
from spotify_manager.routines import scrobble_history
from spotify_manager.routines import something_old
from spotify_manager.settings import Settings


BERLIN = ZoneInfo("Europe/Berlin")
RetryCall = Callable[[Callable[[], Any], str], Any]


class NewYearError(RuntimeError):
    """The retrospective cannot safely continue."""


def validate_state(raw: object) -> dict[str, Any]:
    """Validate annual checkpoints before trusting completion markers."""
    if not isinstance(raw, dict) or not isinstance(raw.get("years"), dict):
        raise NewYearError("Invalid New Year's Routines state.")
    for year, run in raw["years"].items():
        if not str(year).isdigit() or not isinstance(run, dict):
            raise NewYearError("Invalid retrospective year state.")
        if not isinstance(run.get("completed", []), list) or not isinstance(
            run.get("plan", {}), dict
        ):
            raise NewYearError("Invalid retrospective checkpoints.")
    return raw


def rank_year(
    history: tuple[blast_from_past.Scrobble, ...], year: int
) -> dict[str, list[dict[str, Any]]]:
    """Count Berlin calendar-year plays, breaking ties alphabetically."""
    start = int(datetime(year, 1, 1, tzinfo=BERLIN).timestamp() * 1000)
    end = int(datetime(year + 1, 1, 1, tzinfo=BERLIN).timestamp() * 1000)
    counts: dict[str, Counter[tuple[str, ...]]] = {
        "tracks": Counter(),
        "albums": Counter(),
        "artists": Counter(),
    }
    labels: dict[tuple[str, ...], tuple[str, ...]] = {}
    for play in history:
        if not start <= play.timestamp_ms < end:
            continue
        for kind, parts in (
            ("tracks", (play.artist, play.track)),
            ("albums", (play.artist, play.album)),
            ("artists", (play.artist,)),
        ):
            if not all(part.strip() for part in parts):
                continue
            key = tuple(part.strip().casefold() for part in parts)
            counts[kind][key] += 1
            labels.setdefault((kind, *key), parts)
    return {
        kind: [
            {
                "artist": labels[(kind, *key)][0],
                "name": labels[(kind, *key)][-1],
                "scrobbles": count,
            }
            for key, count in sorted(
                counter.items(), key=lambda item: (-item[1], item[0])
            )
        ]
        for kind, counter in counts.items()
    }


def _named_playlist(
    playlists: tuple[queue_3.OwnedPlaylist, ...], name: str
) -> str | None:
    matches = {p.spotify_id for p in playlists if p.name.casefold() == name.casefold()}
    if len(matches) > 1:
        raise NewYearError(
            f'Multiple owned playlists named "{name}"; rename the extras.'
        )
    return next(iter(matches), None)


def _track(sp: Spotify, item: dict[str, Any], retry: RetryCall) -> str:
    matches = blast_from_past.search_spotify_matches(
        sp,
        blast_from_past.Scrobble(
            artist=item["artist"], track=item["name"], album="", timestamp_ms=0
        ),
        retry,
    )
    exact = [m for m in matches if m.track_similarity == 1.0]
    candidates = exact or list(matches)
    if not candidates:
        raise NewYearError(f"No Spotify track match: {item['artist']} — {item['name']}")
    return candidates[0].uri


def _add_missing(
    sp: Spotify,
    playlist_id: str,
    uris: list[str],
    retry: RetryCall,
    *,
    top: bool = False,
) -> None:
    """Reconcile membership before each write, including after partial runs."""

    def add_batch(batch: list[str]) -> None:
        existing = {
            t.uri for t in new_wine.load_playlist_tracks(sp, playlist_id, retry)
        }
        pending = [uri for uri in batch if uri not in existing]
        if not pending:
            return
        payload: dict[str, Any] = {"uris": pending}
        if top:
            payload["position"] = 0
        sp._post(f"playlists/{playlist_id}/items", payload=payload)

    unique = list(dict.fromkeys(uris))
    for offset in range(0, len(unique), 100):
        retry(
            partial(add_batch, unique[offset : offset + 100]),
            "adding retrospective tracks",
        )

    def move_to_front(uri: str) -> None:
        live = new_wine.load_playlist_tracks(sp, playlist_id, retry)
        position = next(i for i, track in enumerate(live) if track.uri == uri)
        if position:
            sp._put(
                f"playlists/{playlist_id}/items",
                payload={
                    "range_start": position,
                    "insert_before": 0,
                    "range_length": 1,
                },
            )

    if top:
        for uri in reversed(unique):
            retry(
                partial(move_to_front, uri),
                "placing yearly artists at the top of Memory Lane",
            )


def run_new_year(
    sp: Spotify,
    lastfm: scrobble_history.LastFmReader,
    configuration: Settings,
    *,
    year: int | None = None,
    dry_run: bool = True,
    state_service: StateService | None = None,
    echo: Callable[[str], None] = print,
    cancel_check: Callable[[], bool] | None = None,
    retry_call: RetryCall | None = None,
) -> dict[str, Any]:
    """Rebuild history, plan all five steps, then apply each once per source year."""
    now = datetime.now(BERLIN)
    year = year if year is not None else now.year - 1
    if year < 2002 or year >= now.year:
        raise NewYearError("Choose a completed calendar year (2002 or later).")

    def retry(operation: Callable[[], Any], description: str) -> Any:
        scrobble_history.check_cancel(cancel_check)
        result = retry_call(operation, description) if retry_call else operation()
        scrobble_history.check_cancel(cancel_check)
        return result

    destinations = {
        "blast": blast_from_past.parse_playlist_id(
            configuration.blast_from_the_past_playlist
        ),
        "palace": blast_from_past.parse_playlist_id(
            configuration.palace_of_memory_playlist
        ),
        "memory": blast_from_past.parse_playlist_id(
            configuration.discography_memory_lane_playlist
        ),
        "queue3": queue_3.parse_playlist_id(configuration.the_queue_3_playlist),
    }
    service = state_service or get_state_service()
    access = service.namespace("new_year", lambda: {"years": {}}, validate_state)
    state = access.load()
    run = state["years"].get(str(year), {"completed": []})
    if run.get("done"):
        echo(f"The {year} retrospective has already completed.")
        return {"year": year, "already_completed": True, **run}
    playlists = queue_3.load_owned_playlists(sp, retry, destinations["queue3"])
    obsessions = _named_playlist(playlists, f"Obsessions {year}")
    if obsessions is None:
        raise NewYearError(
            f'Could not find an owned playlist named "Obsessions {year}".'
        )
    queue_3.find_yearly_great_discoveries(playlists, year)
    if "plan" not in run:
        echo("Rebuilding complete Last.fm history before ranking the previous year")
        history = scrobble_history.refresh_scrobble_history(
            lastfm,
            expected_username=configuration.lastfm_username,
            full_rebuild=True,
            dry_run=dry_run,
            progress_callback=echo,
            cancel_check=cancel_check,
        )
        ranked = rank_year(history.history, year)
        if not ranked["tracks"]:
            raise NewYearError(f"No scrobbles found for {year}.")
        plan: dict[str, Any] = {
            "tracks": ranked["tracks"][:50],
            "albums": ranked["albums"][:20],
            "artists": ranked["artists"][:5],
            "destinations": destinations,
            "obsessions": [
                t.uri for t in new_wine.load_playlist_tracks(sp, obsessions, retry)
            ],
        }
        for item in plan["tracks"]:
            echo(f"Top track: {item['artist']} — {item['name']} ({item['scrobbles']})")
            item["uri"] = _track(sp, item, retry)
        for item in plan["albums"]:
            echo(f"Top album: {item['artist']} — {item['name']} ({item['scrobbles']})")
            album = palace_of_memory.search_spotify_album(
                sp, item["artist"], item["name"], retry
            )
            if album is None:
                raise NewYearError(
                    f"No Spotify album match: {item['artist']} — {item['name']}"
                )
            item["uri"] = palace_of_memory.load_first_track(sp, album, retry).uri
        memory = new_wine.load_playlist_tracks(sp, destinations["memory"], retry)
        for item in plan["artists"]:
            echo(f"Top artist: {item['artist']} ({item['scrobbles']})")
            artist = something_old.resolve_spotify_artist(
                sp, item["artist"], None, retry
            )
            if artist is None:
                raise NewYearError(f"No Spotify artist match: {item['artist']}")
            item["artist_id"] = artist.spotify_id
            marker = next(
                (t.uri for t in memory if t.primary_artist_id == artist.spotify_id),
                None,
            )
            if marker is None:
                for candidate in ranked["tracks"]:
                    if candidate["artist"].casefold() != item["artist"].casefold():
                        continue
                    uri = _track(sp, candidate, retry)
                    raw = retry(
                        partial(sp.track, uri),
                        "checking Memory Lane marker artist",
                    )
                    if raw.get("artists", [{}])[0].get("id") == artist.spotify_id:
                        marker = uri
                        break
            if marker is None:
                raise NewYearError(f"No primary-artist track for {item['artist']}.")
            item["uri"] = marker
        run["plan"] = plan
        if not dry_run:
            state["years"][str(year)] = run
            access.save(state)
    plan = run["plan"]
    if plan["destinations"] != destinations:
        raise NewYearError(
            "Destination settings changed since this retrospective was planned."
        )
    if dry_run:
        queue_3.import_previous_year_discoveries(
            sp,
            destinations["queue3"],
            active_year=year + 1,
            dry_run=True,
            state_service=service,
            retry_call=retry,
            echo=echo,
        )
        echo(
            f"Dry run: {len(plan['tracks'])} tracks, {len(plan['albums'])} albums, "
            f"{len(plan['artists'])} artists and "
            f"{len(plan['obsessions'])} Obsessions tracks."
        )
        return {"year": year, "dry_run": True, **run}

    def checkpoint(step: str, operation: Callable[[], None]) -> None:
        if step in run["completed"]:
            echo(f"Already completed: {step}")
            return
        scrobble_history.check_cancel(cancel_check)
        echo(f"Running: {step}")
        operation()
        run["completed"].append(step)
        access.save(state)

    def chart(kind: str, limit: int, destination: str) -> None:
        name = f"top {limit} {year} {kind}"

        def ensure_chart() -> str:
            owned = queue_3.load_owned_playlists(sp, retry, destinations["queue3"])
            existing = _named_playlist(owned, name)
            if existing is not None:
                return existing
            user = retry(sp.current_user, "loading Spotify owner")
            created = sp.user_playlist_create(
                user["id"],
                name,
                public=False,
                description=f"Most scrobbled {kind} of {year} on Last.fm.",
            )
            return str(created["id"])

        playlist_id = retry(ensure_chart, "finding or creating yearly chart")
        uris = [item["uri"] for item in plan[kind]]
        uris = list(dict.fromkeys(uris))
        current = [t.uri for t in new_wine.load_playlist_tracks(sp, playlist_id, retry)]
        if current != uris:
            retry(
                partial(
                    sp._put, f"playlists/{playlist_id}/items", payload={"uris": uris}
                ),
                "synchronizing the yearly chart in scrobble rank order",
            )
        _add_missing(sp, destination, uris, retry)

    checkpoint("top tracks", lambda: chart("tracks", 50, destinations["blast"]))
    checkpoint("top albums", lambda: chart("albums", 20, destinations["palace"]))
    checkpoint(
        "top artists",
        lambda: _add_missing(
            sp,
            destinations["memory"],
            [i["uri"] for i in plan["artists"]],
            retry,
            top=True,
        ),
    )

    def import_discoveries() -> None:
        queue_3.import_previous_year_discoveries(
            sp,
            destinations["queue3"],
            active_year=year + 1,
            state_service=service,
            retry_call=retry,
            echo=echo,
        )

    checkpoint("Great Discoveries", import_discoveries)
    checkpoint(
        "Obsessions",
        lambda: _add_missing(sp, destinations["blast"], plan["obsessions"], retry),
    )
    run["done"] = True
    access.save(state)
    echo(f"The {year} retrospective is complete.")
    return {"year": year, **run}
