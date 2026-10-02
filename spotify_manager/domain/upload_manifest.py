"""Original deterministic fallback identity and stale-manifest rules."""


class LibraryFilesUploadError(RuntimeError):
    """Report an original preparation or publication failure."""


def part_suffix(index: int) -> str:
    """Encode the original bounded two-letter fallback suffix.

    Args:
        index: Zero-based part identity.

    Returns:
        Original aa through zz suffix.

    Raises:
        LibraryFilesUploadError: The identity exceeds the original range.
    """
    if index < 0 or index >= 26 * 26:
        raise LibraryFilesUploadError(
            "Last.fm export requires too many fallback parts."
        )
    return f"{chr(ord('a') + index // 26)}{chr(ord('a') + index % 26)}"


def stale_parts(
    remote: set[str],
    desired: set[str],
    compressed: str,
    binary_prefix: str,
    encoded_prefix: str,
) -> set[str]:
    """Select original obsolete fallbacks without touching unrelated paths.

    Args:
        remote: Original complete remote file set.
        desired: Original generated part paths.
        compressed: Original monolithic fallback path.
        binary_prefix: Original binary part family.
        encoded_prefix: Original encoded part family.

    Returns:
        Original stale remote fallback set.
    """
    result: set[str] = set()
    if not desired:
        return result
    for path in remote:
        if path == compressed or path.startswith(binary_prefix):
            result.add(path)
            continue
        if path.startswith(encoded_prefix) and path not in desired:
            result.add(path)
    return result
