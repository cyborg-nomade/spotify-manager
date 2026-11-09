"""Present verified history attachments and own temporary response storage."""

from fastapi import HTTPException

from spotify_manager.application.scrobble_download import MissingScrobbleHistoryError
from spotify_manager.application.scrobble_download import (
    prepare_scrobble_history_download,
)
from spotify_manager.bootstrap.scrobble_download import scrobble_downloads
from spotify_manager.core.library_data.models import LibraryDataConfigurationError
from spotify_manager.core.library_data.models import LibraryDataConflictError
from spotify_manager.core.library_data.models import LibraryDataDocumentError
from spotify_manager.core.library_data.models import LibraryDataIntegrityError
from spotify_manager.interfaces.http.scrobble_download_response import (
    ScrobbleHistoryResponse,
)


def download_scrobble_history() -> ScrobbleHistoryResponse:
    """Prepare a read-only attachment in FastAPI's synchronous worker thread.

    Returns:
        Verified JSON attachment with response-owned temporary storage.

    Raises:
        HTTPException: Missing history, publication conflicts, invalid data or storage.
    """
    try:
        snapshot = prepare_scrobble_history_download(scrobble_downloads())
    except MissingScrobbleHistoryError as exc:
        raise HTTPException(404, str(exc)) from exc
    except LibraryDataConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (LibraryDataDocumentError, LibraryDataIntegrityError) as exc:
        raise HTTPException(502, str(exc)) from exc
    except (LibraryDataConfigurationError, OSError) as exc:
        raise HTTPException(
            503, "Stored history could not be downloaded. Try again."
        ) from exc
    return ScrobbleHistoryResponse(snapshot)
