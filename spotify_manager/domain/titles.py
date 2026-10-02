"""Shared conservative title normalization used by history and Spotify matching."""

import re


SLIDING_QUALIFIER = re.compile(
    r"(?:remaster(?:ed)?|live|deluxe|edition|version|mix|mono|stereo|"
    r"anniversary|bonus|reissue|radio|acoustic|explicit|clean|feat(?:uring)?\.?)",
    re.IGNORECASE,
)
BRACKETED_SUFFIX = re.compile(r"\s*[\[(]([^)\]]+)[)\]]\s*$")
DASHED_SUFFIX = re.compile(r"\s+[-\N{EN DASH}\N{EM DASH}]\s+(.+?)\s*$")


def without_sliding_qualifiers(value: str) -> str:
    """Remove recognized trailing edition/version descriptions from a name.

    Args:
        value: Original display title, possibly with several decorated suffixes.

    Returns:
        Title after repeatedly removing only recognized trailing qualifiers.
    """
    result = value.strip()
    while True:
        previous = result
        bracketed = BRACKETED_SUFFIX.search(result)
        if bracketed and SLIDING_QUALIFIER.search(bracketed.group(1)):
            result = result[: bracketed.start()].rstrip()
        dashed = DASHED_SUFFIX.search(result)
        if dashed and SLIDING_QUALIFIER.search(dashed.group(1)):
            result = result[: dashed.start()].rstrip()
        if result == previous:
            return result
