FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY nexora ./nexora
RUN pip install --no-cache-dir '.[postgres]' \
    && useradd --uid 10001 --create-home nexora \
    && mkdir -p /app/data && chown nexora:nexora /app/data
USER nexora
EXPOSE 8051
CMD ["gunicorn", "--bind", "0.0.0.0:8051", "--workers", "1", "--threads", "4", "--timeout", "120", "nexora.src.dash_ui.wsgi:server"]
