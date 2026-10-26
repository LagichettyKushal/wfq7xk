FROM node:22-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/backend/.venv/bin:$PATH"

RUN pip install --no-cache-dir uv
COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN uv sync --project backend --frozen --no-dev

COPY backend/ ./backend/
COPY --from=frontend-build /app/frontend/dist ./frontend-dist/

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
