"""Preserve independent queue rotation, release choices and canonical batch packing."""

from spotify_manager.domain.discography_values import QUEUE_ORDER
from spotify_manager.domain.discography_values import START_QUEUE_ROTATION
from spotify_manager.domain.discography_values import ArtistMarkers
from spotify_manager.domain.discography_values import CatalogRelease
from spotify_manager.domain.discography_values import QueueName


def queue_cycle(start: QueueName) -> tuple[QueueName, ...]:
    """Visit all sources from the persisted or within-run priority.

    Args:
        start: Original first source.

    Returns:
        Original cyclic candidate order.
    """
    index = QUEUE_ORDER.index(start)
    return QUEUE_ORDER[index:] + QUEUE_ORDER[:index]


def next_queue(queue: QueueName) -> QueueName:
    """Advance within-run candidate priority.

    Args:
        queue: Original most recently selected source.

    Returns:
        Original next source for packing.
    """
    return QUEUE_ORDER[(QUEUE_ORDER.index(queue) + 1) % len(QUEUE_ORDER)]


def next_start_queue(queue: QueueName) -> QueueName:
    """Rotate starting priority independently of packing order.

    Args:
        queue: Original persisted first source.

    Returns:
        Original next-run starting priority.
    """
    index = START_QUEUE_ROTATION.index(queue)
    return START_QUEUE_ROTATION[(index + 1) % len(START_QUEUE_ROTATION)]


def selected_releases(
    catalog: tuple[CatalogRelease, ...], identities: tuple[str, ...]
) -> tuple[CatalogRelease, ...] | None:
    """Validate identities and preserve catalog order over interactive choice order.

    Args:
        catalog: Original complete available chronology.
        identities: Original interactive selection.

    Returns:
        Chosen releases in catalog order, or none for invalid identities.
    """
    selected = set(identities)
    available = {release.spotify_id for release in catalog}
    if len(selected) != len(identities) or not selected.issubset(available):
        return None
    result = []
    for release in catalog:
        if release.spotify_id in selected:
            result.append(release)
    return tuple(result)


def removal_markers(markers: tuple[ArtistMarkers, ...]) -> tuple[ArtistMarkers, ...]:
    """Require Newfoundland authority before including Queue 3 removals.

    Args:
        markers: Original complete matching marker groups.

    Returns:
        Original qualified groups in observed order.
    """
    if any(marker.queue == "newfoundland" for marker in markers):
        return markers
    result = []
    for marker in markers:
        if marker.queue != "queue_3":
            result.append(marker)
    return tuple(result)


def parse_indexes(value: str, total: int) -> tuple[int, ...]:
    """Parse ordered unique inclusive release ranges.

    Args:
        value: Original comma-separated indexes and ranges.
        total: Original catalog size.

    Returns:
        Original unique positions in first-requested order.

    Raises:
        ValueError: An index or range is invalid under the original rules.
    """
    indexes: list[int] = []
    seen: set[int] = set()
    for raw in value.split(","):
        _retain_indexes(raw.strip(), total, indexes, seen)
    return tuple(indexes)


def _retain_indexes(part: str, total: int, indexes: list[int], seen: set[int]) -> None:
    if not part:
        return
    for index in _range(part):
        if index < 1 or index > total:
            raise ValueError("release number out of range")
        if index not in seen:
            indexes.append(index)
            seen.add(index)


def _range(part: str) -> range:
    if "-" not in part:
        index = int(part)
        return range(index, index + 1)
    first, last = part.split("-", 1)
    start, end = int(first.strip()), int(last.strip())
    if start > end:
        raise ValueError("range start exceeds range end")
    return range(start, end + 1)


def format_indexes(indexes: tuple[int, ...]) -> str:
    """Compress sorted unique positions without introducing range validation.

    Args:
        indexes: Original arbitrary selected positions.

    Returns:
        Original compact range expression or empty-selection marker.
    """
    if not indexes:
        return "n"
    ordered = sorted(set(indexes))
    ranges: list[str] = []
    start = previous = ordered[0]
    for index in ordered[1:]:
        if index == previous + 1:
            previous = index
            continue
        ranges.append(_formatted_range(start, previous))
        start = previous = index
    ranges.append(_formatted_range(start, previous))
    return ",".join(ranges)


def _formatted_range(start: int, end: int) -> str:
    return str(start) if start == end else f"{start}-{end}"
