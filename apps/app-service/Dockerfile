FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /workspace

COPY libs/database /workspace/libs/database

COPY apps/app-service/pyproject.toml apps/app-service/uv.lock /workspace/apps/app-service/

WORKDIR /workspace/apps/app-service
RUN uv sync --frozen --no-dev

COPY apps/app-service /workspace/apps/app-service

ENV PATH="/workspace/apps/app-service/.venv/bin:$PATH"
ENV PYTHONPATH="/workspace"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]