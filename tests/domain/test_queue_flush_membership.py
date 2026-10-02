"""Protect Queue daily snapshots and original live source-removal semantics."""

from dataclasses import replace

from spotify_manager.domain.queue_flush import daily_sources
from spotify_manager.domain.queue_flush import removable_sources
from spotify_manager.domain.queue_flush import remove_membership
from spotify_manager.domain.queue_flush import source_uris
from tests.support.queue_fill import TRACK
from tests.support.queue_flush import SOURCE


def test_daily_sources_retain_first_marker_and_original_limit() -> None:
    """Skip duplicate artist markers and stop at the tenth distinct primary artist."""
    tracks = [SOURCE, replace(SOURCE, spotify_id="duplicate")]
    for index in range(12):
        tracks.append(
            replace(SOURCE, spotify_id=str(index), primary_artist_id=str(index))
        )
    chosen = daily_sources(tuple(tracks), 10)
    assert len(chosen) == 10
    assert chosen[0] == SOURCE
    assert chosen[-1].spotify_id == "8"


def test_daily_sources_empty_and_zero_limit_keep_original_behavior() -> None:
    """Preserve empty input and original equality-based stopping for a zero limit."""
    assert daily_sources((), 10) == ()
    assert daily_sources((SOURCE,), 0) == (SOURCE,)


def test_source_uris_preserve_order_and_missing_live_source_fallback() -> None:
    """Retain all original live markers for an artist, including duplicate URIs."""
    other = replace(SOURCE, primary_artist_id="other", uri="other")
    assert source_uris((SOURCE, other, SOURCE), SOURCE) == [SOURCE.uri, SOURCE.uri]
    assert source_uris((other,), SOURCE) == [SOURCE.uri]


def test_advance_protects_target_and_retains_removal_duplicates() -> None:
    """Keep the advance target live and preserve ordered original duplicate removals."""
    uris = ["absent", SOURCE.uri, TRACK.uri, SOURCE.uri]
    assert removable_sources(uris, {SOURCE.uri, TRACK.uri}, "advance", TRACK) == [
        SOURCE.uri,
        SOURCE.uri,
    ]
    assert removable_sources(uris, {SOURCE.uri, TRACK.uri}, "promote", TRACK) == [
        SOURCE.uri,
        TRACK.uri,
        SOURCE.uri,
    ]
    assert removable_sources(uris, {SOURCE.uri, TRACK.uri}, "advance", None) == [
        SOURCE.uri,
        TRACK.uri,
        SOURCE.uri,
    ]


def test_membership_removal_uses_first_initial_uri_match_only() -> None:
    """Retain original added-target and duplicate-URI identity behavior."""
    duplicate = replace(SOURCE, spotify_id="duplicate")
    ids = {SOURCE.spotify_id, duplicate.spotify_id, TRACK.spotify_id}
    uris = {SOURCE.uri, TRACK.uri}
    remove_membership((SOURCE, duplicate), [SOURCE.uri, TRACK.uri], ids, uris)
    assert ids == {"duplicate", TRACK.spotify_id}
    assert uris == set()


def test_uri_lookup_skips_initial_nonmatches_before_first_match() -> None:
    """Discard only the first matching initial identity after earlier nonmatches."""
    other = replace(SOURCE, spotify_id="other", uri="other")
    ids = {SOURCE.spotify_id, other.spotify_id}
    remove_membership((other, SOURCE), [SOURCE.uri], ids, {SOURCE.uri, other.uri})
    assert ids == {"other"}
