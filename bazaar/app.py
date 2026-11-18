"""The planner service. Run:  uvicorn bazaar.app:app --port 8000"""
import os, pathlib
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from . import llm, planner

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = pathlib.Path(os.getenv("BAZAAR_DATA", ROOT / "data"))
registry, audit, proposals = planner.Registry(DATA / "registry.json"), planner.Audit(DATA / "audit.jsonl"), {}


@asynccontextmanager
async def lifespan(app):
    for url in filter(None, (u.strip() for u in os.getenv("AGENT_URLS", "").split(","))):
        try:
            registry.register(url, planner.http_transport, audit)
        except Exception as exc:
            print(f"could not register {url}: {exc}")
    yield


app = FastAPI(title="Agent Bazaar planner", lifespan=lifespan)


@app.get("/")
def home():
    return FileResponse(ROOT / "web" / "index.html")


@app.post("/api/plan")
def api_plan(body: dict):
    p = planner.plan(body.get("text", ""), registry, planner.http_transport, audit, llm=llm.parse_with_llm)
    if "error" not in p:
        proposals[p["id"]] = p
    return p


@app.post("/api/confirm")
def api_confirm(body: dict):
    p = proposals.get(body.get("proposal_id"))
    if not p:
        raise HTTPException(404, "Unknown proposal. Run the search again.")
    return planner.confirm(p, registry, planner.http_transport, audit)


@app.get("/api/audit")
def api_audit():
    return {"entries": audit.entries()[-300:], "chain_ok": audit.verify_chain()}


@app.get("/api/registry")
def api_registry():
    return registry.all()


@app.post("/api/registry/register")
def api_register(body: dict):
    try:
        return registry.register(body["base_url"], planner.http_transport, audit)
    except Exception as exc:
        raise HTTPException(400, str(exc))
