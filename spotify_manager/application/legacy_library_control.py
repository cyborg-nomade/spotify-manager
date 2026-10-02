"""Original control decisions, cursor selection and statistics stages."""

from collections.abc import Callable
from collections.abc import Sequence

from spotify_manager.application.legacy_library_effects import Echo
from spotify_manager.domain.legacy_library import LegacyStatistics
from spotify_manager.domain.legacy_library import first_index
from spotify_manager.domain.legacy_library import last_kept_index
from spotify_manager.domain.library_analysis_values import LibraryIdentity
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.stats import StatsFileItem
from spotify_manager.utils.sorting import sort_key


def unevaluated(control: list[ControlFileItem], echo: Echo) -> list[ControlFileItem]:
    """Select the original suffix, including the all-evaluated zero fallback.

    Args:
        control: Original mutable control entries.
        echo: Original presenter.

    Returns:
        The original suffix with shared entry identity.
    """
    echo("Getting unevaluated albums...")
    index = first_index(control_results(control), "")
    echo(f"First unevaluated album index: {index}")
    return control[index:]


def evaluate(
    control: list[ControlFileItem], contains: Callable[[str], object], echo: Echo
) -> list[ControlFileItem]:
    """Mutate original control entries after each live membership read.

    Args:
        control: Original mutable entries.
        contains: Original singleton membership query.
        echo: Original presenter.

    Returns:
        The same control list.
    """
    echo("Checking against library...")
    for item in control:
        item.result = "keep" if contains(item.album.spotify_id) else "remove"
        echo(f"album:{item.album.name}: result: {item.result}")
    return control


def reconcile(
    albums: list[SimplifiedAlbum],
    decisions: list[ControlFileItem],
    save: Callable[[list[SimplifiedAlbum]], None],
) -> None:
    """Remove original rejected entries before sorted publication.

    Args:
        albums: Original mutable album authority.
        decisions: Original observed decisions.
        save: Original publication boundary.

    Raises:
        IndexError: An original removal targets an empty authority.
    """
    for item in decisions:
        if item.result != "remove":
            continue
        index = first_index(album_ids(albums), item.album.spotify_id)
        albums.pop(index)
    save(sorted(albums, key=sort_key))


def check(
    control: list[ControlFileItem],
    albums: list[SimplifiedAlbum],
    select: Callable[[list[ControlFileItem]], list[ControlFileItem]],
    observe: Callable[[list[ControlFileItem]], list[ControlFileItem]],
    update: Callable[[list[SimplifiedAlbum], list[ControlFileItem]], None],
    save: Callable[[list[ControlFileItem]], None],
    echo: Echo,
) -> bool:
    """Retain original public stage seams and accepted effect order.

    Args:
        control: Original control authority.
        albums: Original album authority.
        select: Original suffix selection.
        observe: Original live decision stage.
        update: Original album reconciliation.
        save: Original control publication.
        echo: Original presenter.

    Returns:
        True after the original complete sequence.
    """
    echo("Checking album results...")
    selected = select(control)
    observe(selected)
    update(albums, selected)
    save(control)
    echo("Results checked!")
    return True


def starting_index(
    control: list[ControlFileItem], albums: list[SimplifiedAlbum], echo: Echo
) -> int:
    """Retain last-kept lookup and the original one-based continuation.

    Args:
        control: Original decisions.
        albums: Original album authority.
        echo: Original presenter.

    Returns:
        First matching album index plus one, including the fallback.

    Raises:
        IndexError: Original control authority is empty.
    """
    echo("Getting starting index...")
    index = last_kept_index(control_results(control))
    echo("last_kept_album_item_index: ", index)
    identifier = control[index].album.spotify_id
    return first_index(album_ids(albums), identifier) + 1


def calculate(
    control: list[ControlFileItem], albums: list[SimplifiedAlbum], echo: Echo
) -> StatsFileItem:
    """Build original statistics without changing zero-denominator behavior.

    Args:
        control: Original decisions.
        albums: Original album authority.
        echo: Original presenter.

    Returns:
        Unchanged public statistics model.

    Raises:
        ZeroDivisionError: An original denominator is zero.
    """
    echo("Calculating stats...")
    saved = len(albums)
    listened = len(control)
    removed = 0
    for item in control:
        if item.result == "remove":
            removed += 1
    counts = LegacyStatistics(saved, listened, removed)
    return StatsFileItem.model_validate(counts.fields())


def update_statistics(
    control: list[ControlFileItem],
    albums: list[SimplifiedAlbum],
    calculate: Callable[[list[ControlFileItem], list[SimplifiedAlbum]], StatsFileItem],
    save: Callable[[StatsFileItem], None],
    echo: Echo,
) -> bool:
    """Publish original statistics after displaying the complete model.

    Args:
        control: Original decisions.
        albums: Original album authority.
        calculate: Original public calculation seam.
        save: Original statistics publication.
        echo: Original presenter.

    Returns:
        True after accepted publication.
    """
    echo("Updating stats...")
    stats = calculate(control, albums)
    echo(f"These are your current stats: \n{stats.model_dump()}")
    save(stats)
    echo("Stats updated!")
    return True


def control_results(control: list[ControlFileItem]) -> list[str]:
    """Read original decision strings in encounter order.

    Args:
        control: Original control entries.

    Returns:
        Every original decision, including unrecognized values.
    """
    return [item.result for item in control]


def album_ids(albums: Sequence[LibraryIdentity]) -> list[str]:
    """Read original identities without deduplication.

    Args:
        albums: Original ordered album entries.

    Returns:
        Every original identity in encounter order.
    """
    return [album.spotify_id for album in albums]
