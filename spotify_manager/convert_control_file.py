"""Convert control file to JSON standard."""

from spotify_manager.models.file_items import ControlFileItem


def extract_initial_data(file_path: str) -> list[ControlFileItem]:
    """Extract data in the initial control file and return a list of ControlFileItem."""

    with open(file_path, "r") as initial_control_file:
        lines = initial_control_file.readlines()
        print(lines)

    return []


if __name__ == "__main__":
    extract_initial_data(
        "/home/ufiori/dev/spotify-manager/spotify_manager/"
        "files/Spotify Albuns (03-11-2020).txt"
    )
