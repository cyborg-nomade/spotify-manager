"""Utils for sorting lists alphabetically."""
import re
import unicodedata

from unidecode import unidecode

latin_letters: dict = {}


def is_latin(unicode_char: str) -> bool:
    """Return whether a character is in the Latin subset of unicode."""
    try:
        return latin_letters[unicode_char]
    except KeyError:
        return latin_letters.setdefault(
            unicode_char, "LATIN" in unicodedata.name(unicode_char)
        )


def is_all_latin(string: str) -> bool:
    """Return whether a string is made up of only latin characters."""
    return all(
        is_latin(unicode_char) for unicode_char in string if unicode_char.isalpha()
    )


def get_ordering_string(album_name: str) -> str:
    """Return the ordering string from the album name."""
    pattern = re.compile(r"(^(the|a|an)\b)?(?!\$)\W|_", re.UNICODE | re.IGNORECASE)

    tentative_ordering_str = re.sub(pattern, "", album_name)

    if tentative_ordering_str:
        if is_all_latin(tentative_ordering_str):
            tentative_ordering_str = unidecode(tentative_ordering_str)
        return tentative_ordering_str.upper()
    else:
        return album_name.upper()
