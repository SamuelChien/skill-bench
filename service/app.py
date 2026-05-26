from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from service import db
from service.routes import jobs, results, skills, tasks
from service.worker import start_workers, stop_workers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    await start_workers()
    yield
    await stop_workers()
    await db.close_db()


app = FastAPI(
    title="skill-bench",
    description="Eval benchmark service for Claude skills",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(tasks.router)
app.include_router(skills.router)
app.include_router(jobs.router)
app.include_router(results.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


def run():
    uvicorn.run("service.app:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    run()
