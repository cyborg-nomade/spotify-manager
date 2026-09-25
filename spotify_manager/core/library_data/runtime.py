"""Legacy imports for library composition, owned by the outer bootstrap."""

from spotify_manager.bootstrap.library_data import (
    DEFAULT_ARTIFACT_PATHS as DEFAULT_ARTIFACT_PATHS,
)
from spotify_manager.bootstrap.library_data import (
    DEFAULT_LIBRARY_DATA_LOCAL_ROOT as DEFAULT_LIBRARY_DATA_LOCAL_ROOT,
)
from spotify_manager.bootstrap.library_data import (
    DEFAULT_LIBRARY_DATA_MANIFEST as DEFAULT_LIBRARY_DATA_MANIFEST,
)
from spotify_manager.bootstrap.library_data import (
    DEFAULT_LIBRARY_DATA_REPO as DEFAULT_LIBRARY_DATA_REPO,
)
from spotify_manager.bootstrap.library_data import FILES_DIR as FILES_DIR
from spotify_manager.bootstrap.library_data import (
    artifact_for_path as artifact_for_path,
)
from spotify_manager.bootstrap.library_data import (
    get_library_data_service as get_library_data_service,
)
from spotify_manager.bootstrap.library_data import (
    hydrate_runtime_library_data as hydrate_runtime_library_data,
)
from spotify_manager.bootstrap.library_data import (
    publish_managed_path as publish_managed_path,
)
from spotify_manager.bootstrap.library_data import (
    reset_library_data_service as reset_library_data_service,
)
