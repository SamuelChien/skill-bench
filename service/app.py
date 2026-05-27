from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from pathlib import Path

import anthropic
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from service import db
from service.config import settings
from service.routes import jobs, mining, results, skills, tasks
from service.worker import start_workers, stop_workers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("skill-bench")


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "path": request.url.path},
    )


app.include_router(tasks.router)
app.include_router(skills.router)
app.include_router(jobs.router)
app.include_router(results.router)
app.include_router(mining.router)

_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(str(_static_dir / "index.html"))


@app.get("/health")
async def health():
    api_key = settings.get_api_key()
    return {
        "status": "ok",
        "api_key_set": bool(api_key),
        "database": settings.database_path,
        "workers": settings.num_workers,
    }


@app.get("/health/api")
async def health_api():
    api_key = settings.get_api_key()
    if not api_key:
        return JSONResponse(status_code=503, content={"status": "no_api_key"})
    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=5,
            messages=[{"role": "user", "content": "hi"}],
        )
        return {"status": "ok", "model": "claude-haiku-4-5-20251001"}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "error", "detail": str(e)})


def run():
    uvicorn.run("service.app:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    run()
