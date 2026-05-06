"""Job tray JSON, SSE stream, global cost summary."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from jobs import cost_ledger
from jobs.runner import get_runner

router = APIRouter()


@router.get("/jobs")
def jobs_index():
    runner = get_runner()
    return JSONResponse({"jobs": [j.to_dict() for j in runner.all_jobs()]})


@router.get("/jobs/{job_id}")
def job_detail(job_id: str):
    runner = get_runner()
    j = runner.get(job_id)
    if not j:
        raise HTTPException(404, f"No such job {job_id}")
    return JSONResponse({**j.to_dict(), "log": list(j.log)})


@router.post("/jobs/{job_id}/kill")
def job_kill(job_id: str):
    runner = get_runner()
    if not runner.kill(job_id):
        raise HTTPException(404, f"No such job {job_id}")
    return JSONResponse({"ok": True})


@router.get("/events/jobs")
async def events_jobs(request: Request):
    runner = get_runner()

    async def stream():
        snapshot = {"jobs": [j.to_dict() for j in runner.all_jobs()]}
        yield f"event: snapshot\ndata: {json.dumps(snapshot)}\n\n"
        q = runner.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"event: job\ndata: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            runner.unsubscribe(q)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/cost-summary")
def cost_summary():
    return JSONResponse(cost_ledger.summary())
