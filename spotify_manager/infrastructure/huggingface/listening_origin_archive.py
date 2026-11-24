"""Persist validated origin evidence in a sidecar of the private data dataset."""

import asyncio
import gzip
import json
from dataclasses import asdict
from datetime import datetime
from io import BytesIO
from pathlib import Path

from httpx import HTTPError
from huggingface_hub import CommitOperationAdd
from huggingface_hub import HfApi
from huggingface_hub import hf_hub_download
from huggingface_hub.errors import HfHubHTTPError
from huggingface_hub.errors import RemoteEntryNotFoundError

from spotify_manager.application.listening_origin_ports import OriginCacheError
from spotify_manager.domain.listening_origin_values import ArtistOriginMetadata
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.listening.origin_cache import MAX_CACHED_ARTISTS
from spotify_manager.infrastructure.listening.origin_cache import decode_origin_metadata
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


PATH = "derived/artist-origins-v1.jsonl.gz"
MAX_DOCUMENT = 32768
MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024


def _load(path: Path) -> tuple[ArtistOriginMetadata, ...]:
    entries: dict[str, ArtistOriginMetadata] = {}
    size = 0
    with gzip.open(path, "rb") as source:
        while line := source.readline(MAX_DOCUMENT + 1):
            size += len(line)
            if (
                len(line) > MAX_DOCUMENT
                or len(entries) >= MAX_CACHED_ARTISTS
                or size > MAX_CHECKPOINT_BYTES
            ):
                raise ValueError("Country checkpoint exceeded its bounds.")
            row = decode_origin_metadata(line.decode())
            if row.artist_key in entries:
                raise ValueError("Country checkpoint contains duplicate artists.")
            entries[row.artist_key] = row
    return tuple(entries.values())


def _merge(
    old: tuple[ArtistOriginMetadata, ...], new: tuple[ArtistOriginMetadata, ...]
) -> tuple[ArtistOriginMetadata, ...]:
    entries = {item.artist_key: item for item in old}
    for item in new:
        previous = entries.get(item.artist_key)
        if previous is None or datetime.fromisoformat(
            item.fetched_at
        ) >= datetime.fromisoformat(previous.fetched_at):
            entries[item.artist_key] = item
    if len(entries) > MAX_CACHED_ARTISTS:
        raise ValueError("Country checkpoint has reached its artist limit.")
    return tuple(entries[key] for key in sorted(entries))


def _encode(entries: tuple[ArtistOriginMetadata, ...]) -> bytes:
    if len(entries) > MAX_CACHED_ARTISTS:
        raise ValueError("Country checkpoint has reached its artist limit.")
    destination = BytesIO()
    size = 0
    with gzip.GzipFile(
        fileobj=destination, mode="wb", compresslevel=4, mtime=0
    ) as archive:
        for item in entries:
            document = json.dumps(asdict(item), ensure_ascii=False)
            decode_origin_metadata(document)
            line = document.encode() + b"\n"
            size += len(line)
            if len(line) > MAX_DOCUMENT or size > MAX_CHECKPOINT_BYTES:
                raise ValueError("Country checkpoint contains oversized evidence.")
            archive.write(line)
    return destination.getvalue()


class HubOriginArchive:
    """Store resumable checkpoints without editing the canonical data manifest."""

    def __init__(self, dataset: str, token: str | None) -> None:
        """Bind the configured data repository and its existing server credential."""
        self._dataset, self._token = dataset, token
        self._api = HfApi(token=token)

    def _head(self) -> str:
        info = self._api.repo_info(self._dataset, repo_type="dataset")
        if not info.private or not info.sha:
            raise OriginCacheError(
                "Country checkpoints require a readable private dataset."
            )
        return info.sha

    def _read(self, head: str) -> tuple[ArtistOriginMetadata, ...]:
        try:
            path = hf_hub_download(
                self._dataset,
                PATH,
                repo_type="dataset",
                revision=head,
                token=self._token,
            )
        except RemoteEntryNotFoundError:
            return ()
        return _load(Path(path))

    def _restore(self) -> tuple[ArtistOriginMetadata, ...]:
        try:
            return self._read(self._head())
        except HfHubHTTPError, HTTPError, OSError, EOFError, ValueError:
            raise OriginCacheError(
                "Could not read the durable Artist Map checkpoint."
            ) from None

    def _publish(
        self, entries: tuple[ArtistOriginMetadata, ...]
    ) -> tuple[ArtistOriginMetadata, ...]:
        try:
            return self._commit_with_rebase(entries)
        except HfHubHTTPError, HTTPError, OSError, EOFError, ValueError:
            raise OriginCacheError(
                "Could not save the durable Artist Map checkpoint."
            ) from None

    def _commit_with_rebase(
        self, entries: tuple[ArtistOriginMetadata, ...]
    ) -> tuple[ArtistOriginMetadata, ...]:
        for _ in range(3):
            head = self._head()
            prior = self._read(head)
            merged = _merge(prior, entries)
            try:
                self._commit(head, merged)
            except HfHubHTTPError as error:
                if error.response.status_code not in (409, 412):
                    raise
                continue
            return merged
        raise OriginCacheError(
            "The durable dataset changed repeatedly during the Artist Map checkpoint."
        )

    def _commit(self, head: str, entries: tuple[ArtistOriginMetadata, ...]) -> None:
        self._api.create_commit(
            self._dataset,
            repo_type="dataset",
            parent_commit=head,
            operations=[
                CommitOperationAdd(path_in_repo=PATH, path_or_fileobj=_encode(entries))
            ],
            commit_message="Checkpoint Artist Map country evidence",
        )

    async def restore(self) -> tuple[ArtistOriginMetadata, ...]:
        """Restore a committed checkpoint off the event loop."""
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._restore))
            return await finish_blocking(task)

    async def checkpoint(
        self, entries: tuple[ArtistOriginMetadata, ...]
    ) -> tuple[ArtistOriginMetadata, ...]:
        """Commit a checkpoint and preserve concurrent dataset writes.

        Args:
            entries: Successfully completed lookups to merge.

        Returns:
            The complete committed evidence after conflict resolution.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._publish, entries))
            return await finish_blocking(task)
