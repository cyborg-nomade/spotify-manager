"""Original control decisions, cursor selection and statistics stages."""

from collections.abc import Sequence

from spotify_manager.application.legacy_library_effects import ControlMembership
from spotify_manager.application.legacy_library_effects import Echo
from spotify_manager.application.legacy_library_effects import LegacyFiles
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
    echo.echo("Getting unevaluated albums...")
    index = first_index(control_results(control), "")
    echo.echo(f"First unevaluated album index: {index}")
    return control[index:]


async def evaluate(
    control: list[ControlFileItem], catalog: ControlMembership, echo: Echo
) -> list[ControlFileItem]:
    """Mutate original control entries after each live membership read.

    Args:
        control: Original mutable entries.
        catalog: Singleton membership reader.
        echo: Original presenter.

    Returns:
        The same control list.
    """
    echo.echo("Checking against library...")
    for item in control:
        item.result = (
            "keep" if (await catalog.contains(item.album.spotify_id)) else "remove"
        )
        echo.echo(f"album:{item.album.name}: result: {item.result}")
    return control


async def reconcile(
    albums: list[SimplifiedAlbum],
    decisions: list[ControlFileItem],
    files: LegacyFiles,
) -> None:
    """Remove original rejected entries before sorted publication.

    Args:
        albums: Original mutable album authority.
        decisions: Original observed decisions.
        files: Album publication owner.

    Raises:
        IndexError: An original removal targets an empty authority.
    """
    for item in decisions:
        if item.result != "remove":
            continue
        index = first_index(album_ids(albums), item.album.spotify_id)
        albums.pop(index)
    await files.save_albums(sorted(albums, key=sort_key))


async def check(
    control: list[ControlFileItem],
    albums: list[SimplifiedAlbum],
    catalog: ControlMembership,
    files: LegacyFiles,
    echo: Echo,
) -> bool:
    """Retain original public stage seams and accepted effect order.

    Args:
        control: Original control authority.
        albums: Original album authority.
        catalog: Singleton membership reader.
        files: Album and control publication owner.
        echo: Original presenter.

    Returns:
        True after the original complete sequence.
    """
    echo.echo("Checking album results...")
    selected = unevaluated(control, echo)
    await evaluate(selected, catalog, echo)
    await reconcile(albums, selected, files)
    await files.save_control(control)
    echo.echo("Results checked!")
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
    echo.echo("Getting starting index...")
    index = last_kept_index(control_results(control))
    echo.echo("last_kept_album_item_index: ", index)
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
    echo.echo("Calculating stats...")
    saved = len(albums)
    listened = len(control)
    removed = 0
    for item in control:
        if item.result == "remove":
            removed += 1
    counts = LegacyStatistics(saved, listened, removed)
    return StatsFileItem.model_validate(counts.fields())


async def update_statistics(
    control: list[ControlFileItem],
    albums: list[SimplifiedAlbum],
    files: LegacyFiles,
    echo: Echo,
) -> bool:
    """Publish original statistics after displaying the complete model.

    Args:
        control: Original decisions.
        albums: Original album authority.
        files: Statistics publication owner.
        echo: Original presenter.

    Returns:
        True after accepted publication.
    """
    echo.echo("Updating stats...")
    stats = calculate(control, albums, echo)
    echo.echo(f"These are your current stats: \n{stats.model_dump()}")
    await files.save_stats(stats)
    echo.echo("Stats updated!")
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
