"""HTTP API, plus the mobile web app as static files. Run: uvicorn finn.api:app"""
import os
import threading
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import research, service
from .config import ROOT


class Feedback(BaseModel):
    category: str
    more: bool


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("FINN_SCHEDULER", "1") == "1":
        threading.Thread(target=service.scheduler, daemon=True).start()
    yield


app = FastAPI(title="FINN", lifespan=lifespan)


def _company(fn, symbol: str):
    try:
        return fn(symbol.upper())
    except requests.HTTPError as e:
        raise HTTPException(404 if e.response.status_code == 404 else 502, f"Could not load {symbol.upper()} from screener.in")
    except Exception as e:  # e.g. a model or network failure: say what failed instead of a bare 500
        raise HTTPException(502, f"{type(e).__name__}: {e}"[:300])


@app.get("/api/digest")
def digest(hours: int = 24):
    return service.digest(hours)


@app.get("/api/alerts")
def alerts(days: int = 7):
    return service.alerts(days)


@app.get("/api/status")
def status():
    return service.status()


@app.get("/api/settings")
def get_settings():
    return service.settings()


@app.put("/api/settings")
def put_settings(changes: dict):
    return service.save_settings(changes)


@app.post("/api/feedback")
def feedback(body: Feedback):
    return service.feedback(body.category, body.more)


@app.post("/api/refresh")
def refresh(prices: bool = False):
    service.run_jobs(rescan_prices=prices)
    return service.status()


@app.get("/api/company/{symbol}")
def company(symbol: str):
    return _company(research.snapshot, symbol)


@app.post("/api/company/{symbol}/ledger")
def ledger(symbol: str):
    return _company(research.build_ledger, symbol)


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
