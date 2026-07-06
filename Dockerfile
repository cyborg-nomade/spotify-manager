# Hugging Face Spaces (Docker SDK) image for Spotify Manager.
#
# The app's file loaders use absolute paths under
#   /Users/uriel.fiori/dev/spotify-manager/spotify_manager/files/...
# so we deliberately place the project at that exact path (WORKDIR) to keep
# them working without touching the application code. See DEPLOY.md.

FROM python:3.14-slim

# uv for fast, lockfile-faithful installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1

# Match the hardcoded absolute paths in the loaders.
ARG APP_HOME=/Users/uriel.fiori/dev/spotify-manager
WORKDIR ${APP_HOME}

# Install dependencies first (cached layer) using only the lockfile + manifest.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --python /usr/local/bin/python3

# Copy the project and install it into the environment.
COPY . .
RUN uv sync --frozen --no-dev --python /usr/local/bin/python3

# Run as a non-root user (UID 1000, as recommended for HF Spaces) and make the
# project tree writable so the command endpoints can rewrite the data files.
RUN useradd -m -u 1000 appuser \
    && chmod +x start.sh \
    && chown -R appuser:appuser ${APP_HOME}
USER appuser

ENV PATH="${APP_HOME}/.venv/bin:${PATH}"

EXPOSE 7860
CMD ["./start.sh"]
