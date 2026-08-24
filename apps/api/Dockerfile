FROM python:3.12-slim

ARG BUILD_VERSION=dev
LABEL org.opencontainers.image.title="Parloq Flow API" \
      org.opencontainers.image.revision="${BUILD_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY vendor/phonenumberslite/phonenumberslite-9.0.34-py2.py3-none-any.whl ./vendor/phonenumberslite/
RUN pip install --no-cache-dir ./vendor/phonenumberslite/phonenumberslite-9.0.34-py2.py3-none-any.whl
COPY app ./app
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY alembic ./alembic

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
