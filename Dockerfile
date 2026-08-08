FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /srv
ENV UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
# games/ is baked in as a fallback; in production the app reads game files
# from GitHub raw (GITHUB_REPO), so agent releases go live without a redeploy.
COPY games ./games

ENV PATH="/srv/.venv/bin:$PATH"
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
