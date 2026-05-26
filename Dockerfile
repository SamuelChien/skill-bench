FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY engine/ engine/
COPY service/ service/
RUN pip install --no-cache-dir .

COPY tasks/ tasks/
COPY skills/ skills/

RUN mkdir -p /app/results

EXPOSE 8000

ENTRYPOINT ["skill-bench-server"]
