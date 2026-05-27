FROM node:20-slim AS node-base

FROM python:3.12-slim

COPY --from=node-base /usr/local/bin/node /usr/local/bin/node
COPY --from=node-base /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

COPY pyproject.toml .
COPY engine/ engine/
COPY service/ service/
RUN pip install --no-cache-dir .

COPY tasks/ tasks/
COPY skills/ skills/

ENV PORT=8080
EXPOSE 8080

CMD ["python3", "-m", "uvicorn", "service.app:app", "--host", "0.0.0.0", "--port", "8080"]
