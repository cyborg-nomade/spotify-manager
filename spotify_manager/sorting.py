"""Utils for sorting lists alphabetically."""
import re


def get_ordering_string(album_name: str) -> str:
    """Return the ordering string from the album name."""
    pattern = re.compile(r"(^(the|a|an)\b)?\W*", re.UNICODE | re.IGNORECASE)

    tentative_ordering_str = re.sub(pattern, "", album_name)

    if tentative_ordering_str:
        return tentative_ordering_str.upper()
    else:
        return album_name.upper()
