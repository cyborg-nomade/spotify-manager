"""Ensure router extraction cannot hide changed public registration metadata."""

import pytest
from fastapi import APIRouter
from fastapi import FastAPI

from docs.refactor.capture_baseline import route_inventory
from spotify_manager.interfaces.http.models.common import CountResult


def _endpoint() -> CountResult:
    return CountResult(count=1)


def _routes(router: APIRouter) -> None:
    router.add_api_route("/first", _endpoint, methods=["GET"], status_code=201)
    router.add_api_route("/second", _endpoint, methods=["POST"])
    router.add_api_route("/hidden", _endpoint, methods=["PUT"], include_in_schema=False)


@pytest.mark.parametrize("included", [False, True])
def test_direct_and_included_metadata_keep_original_order(included: bool) -> None:
    """Read direct and lazy included registrations without omitting hidden paths.

    Args:
        included: Whether the framework uses an included router context.
    """
    app = FastAPI()
    if included:
        router = APIRouter()
        _routes(router)
        app.include_router(router)
    else:
        _routes(app.router)
    rows = route_inventory(app, "fixture")
    assert [row["path"] for row in rows][-3:] == ["/first", "/second", "/hidden"]
    assert rows[-3]["declared_status_code"] == 201
    assert rows[-2]["declared_status_code"] is None
    assert rows[-1]["include_in_schema"] is False
    assert rows[-1]["methods"] == ["PUT"]
    assert rows[-1]["handler"] == f"{__name__}._endpoint"
    assert rows[-1]["response_model"] == "CountResult"


def test_composed_prefix_and_parent_options_are_observed() -> None:
    """Retain nested prefixes, declared statuses and hidden parent options."""
    inner, outer = APIRouter(), APIRouter()
    _routes(inner)
    outer.include_router(inner, prefix="/inner")
    app = FastAPI()
    app.include_router(outer, prefix="/outer", include_in_schema=False)
    rows = route_inventory(app, "fixture")[-3:]
    assert [row["path"] for row in rows] == [
        "/outer/inner/first",
        "/outer/inner/second",
        "/outer/inner/hidden",
    ]
    assert [row["declared_status_code"] for row in rows] == [201, None, None]
    assert [row["include_in_schema"] for row in rows] == [False, False, False]
