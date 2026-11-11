FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/service

WORKDIR /service
# The package MUST be present when pip installs it. In the previous Dockerfile
# pyproject.toml was installed first and app/ was copied afterwards, leaving
# imports unregistered for the pytest console entrypoint.
COPY . .
RUN python -m pip install --no-cache-dir ".[dev]" \
    && useradd --uid 10001 --create-home appuser

USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
