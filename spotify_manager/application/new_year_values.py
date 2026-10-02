"""Original annual errors and known written plan/checkpoint fields."""

from typing import TypedDict

from spotify_manager.domain.annual_history import YearEntry


class NewYearError(RuntimeError):
    """The retrospective cannot safely continue."""


class RetrospectivePlan(TypedDict):
    """Describe complete original plan fields without validating legacy resumed values.

    Args:
        tracks: Original at-most-fifty ranked resolved track records.
        albums: Original at-most-twenty ranked resolved first-album-marker records.
        artists: Original at-most-five ranked resolved primary artist markers.
        destinations: Original exact planned destination settings.
        obsessions: Original complete ordered source URIs, including duplicates.
    """

    tracks: list[YearEntry]
    albums: list[YearEntry]
    artists: list[YearEntry]
    destinations: dict[str, str]
    obsessions: list[str]


class RetrospectiveRun(TypedDict, total=False):
    """Describe known original annual checkpoint fields while retaining unknown fields.

    Args:
        completed: Original shallow-validated completion list.
        plan: Original resolved plan, retaining original resumed record tolerance.
        done: Original truthiness-based completion authority.
    """

    completed: list[object]
    plan: RetrospectivePlan
    done: object


class RetrospectiveState(TypedDict):
    """Describe the original annual namespace without adding validation to stored plans.

    Args:
        years: Original digit-keyed shallow-validated annual records.
    """

    years: dict[str, RetrospectiveRun]
