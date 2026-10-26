"""Named external mock responses that ignore original request arguments."""


def empty_object(*args: object, **kwargs: object) -> dict[str, object]:
    """Return a fresh invalid or empty JSON response for an external mock API.

    Args:
        args: Ignored original request values supplied by Mock.
        kwargs: Ignored original request options supplied by Mock.

    Returns:
        Fresh original empty response object.
    """
    return {}


def empty_list(*args: object, **kwargs: object) -> list[object]:
    """Return a fresh empty response for an external mock API.

    Args:
        args: Ignored original request values supplied by Mock.
        kwargs: Ignored original request options supplied by Mock.

    Returns:
        Fresh original empty response list.
    """
    return []


def snapshot_items[T](snapshots: list[list[T]], items: list[T]) -> None:
    """Record a detached item list at the original external mock write boundary.

    Args:
        snapshots: Original accepted-write observations.
        items: Original values supplied to the mocked writer.
    """
    snapshots.append(list(items))
