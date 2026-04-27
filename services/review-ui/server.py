"""Board Factory review UI.

Three view modes optimized for three asset categories:
- /spaces: grid view, all unique designs visible at once
- /panels/<id>: per-panel carousel, all candidates side-by-side
- /centerpiece: mask-and-refine, single asset with iterative inpainting

The UI reads cleaned candidates from workspace/cleaned/ and writes approvals to
workspace/approved/. For centerpiece refinement it talks directly to PixelLab
so the user can iterate without going back to the CLI.
"""

from __future__ import annotations

import base64
import io
import json
import os
import shutil
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image

REPO_ROOT = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))
CATALOG_PATH = REPO_ROOT / "catalog" / "board.yml"
WORKSPACE = REPO_ROOT / "workspace"
CLEANED = WORKSPACE / "cleaned"
APPROVED = WORKSPACE / "approved"
REFINEMENTS = WORKSPACE / "refinements"
STYLE_DIR = WORKSPACE / "style"

app = FastAPI(title="Board Factory Review")

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ────────────────────────── helpers ──────────────────────────


def _load_catalog() -> dict:
    if not CATALOG_PATH.exists():
        raise HTTPException(404, f"Catalog not found at {CATALOG_PATH}")
    with open(CATALOG_PATH) as f:
        return yaml.safe_load(f)


def _candidates(category: str, asset_id: str | None = None) -> list[Path]:
    base = CLEANED / category
    if asset_id:
        base = base / asset_id
    if not base.exists():
        return []
    return sorted(p for p in base.glob("*.png") if not p.name.startswith("_"))


def _approved_path(category: str, asset_id: str) -> Path:
    if category == "centerpiece":
        return APPROVED / "centerpiece.png"
    return APPROVED / category / f"{asset_id}.png"


def _is_approved(category: str, asset_id: str) -> Path | None:
    p = _approved_path(category, asset_id)
    return p if p.exists() else None


def _safe_workspace_path(rel: str) -> Path:
    """Resolve a workspace-relative path safely (no traversal outside workspace)."""
    target = (WORKSPACE / rel).resolve()
    if not str(target).startswith(str(WORKSPACE.resolve())):
        raise HTTPException(400, "Invalid path")
    return target


def _palette_for_provider() -> list[tuple[int, int, int]] | None:
    pal_path = STYLE_DIR / "palette.json"
    if not pal_path.exists():
        return None
    return [tuple(c) for c in json.loads(pal_path.read_text())]


# ────────────────────────── routes ──────────────────────────


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    catalog = _load_catalog()
    designs = catalog["board_spaces"]["designs"]
    panels = catalog["feature_panels"]["panels"]

    space_status = []
    for d in designs:
        approved_p = _is_approved("spaces", d["id"])
        space_status.append({
            "id": d["id"],
            "approved": bool(approved_p),
            "candidates": len(_candidates("spaces", d["id"])),
            "uses": len(d.get("positions", [])),
        })

    panel_status = []
    for p in panels:
        approved_p = _is_approved("panels", p["id"])
        panel_status.append({
            "id": p["id"],
            "approved": bool(approved_p),
            "candidates": len(_candidates("panels", p["id"])),
        })

    cp_approved = (APPROVED / "centerpiece.png").exists()
    cp_candidates = len(_candidates("centerpiece"))
    cp_refinements = sorted(REFINEMENTS.glob("centerpiece_v*.png")) if REFINEMENTS.exists() else []

    return templates.TemplateResponse("index.html", {
        "request": request,
        "project": catalog.get("project", "board"),
        "spaces": space_status,
        "panels": panel_status,
        "centerpiece": {
            "approved": cp_approved,
            "candidates": cp_candidates,
            "refinements": len(cp_refinements),
        },
    })


@app.get("/spaces", response_class=HTMLResponse)
def spaces_view(request: Request):
    catalog = _load_catalog()
    designs = catalog["board_spaces"]["designs"]
    rows = []
    for d in designs:
        candidates = _candidates("spaces", d["id"])
        approved = _is_approved("spaces", d["id"])
        approved_name = approved.name if approved else None
        # Heuristic: pick approved by matching name back to candidate.
        approved_idx = None
        if approved:
            try:
                approved_bytes = approved.read_bytes()
                for i, c in enumerate(candidates):
                    if c.read_bytes() == approved_bytes:
                        approved_idx = i
                        break
            except OSError:
                pass
        rows.append({
            "id": d["id"],
            "prompt": d["prompt"],
            "uses": len(d.get("positions", [])),
            "candidates": [c.name for c in candidates],
            "approved_idx": approved_idx,
        })
    return templates.TemplateResponse("spaces.html", {
        "request": request,
        "designs": rows,
    })


@app.post("/spaces/{design_id}/approve")
def approve_space(design_id: str, candidate: str = Form(...)):
    src = CLEANED / "spaces" / design_id / candidate
    if not src.exists():
        raise HTTPException(404, f"No such candidate {candidate}")
    dst = _approved_path("spaces", design_id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return RedirectResponse("/spaces", status_code=303)


@app.post("/spaces/{design_id}/unapprove")
def unapprove_space(design_id: str):
    dst = _approved_path("spaces", design_id)
    if dst.exists():
        dst.unlink()
    return RedirectResponse("/spaces", status_code=303)


@app.get("/panels/{panel_id}", response_class=HTMLResponse)
def panel_view(request: Request, panel_id: str):
    catalog = _load_catalog()
    panels = catalog["feature_panels"]["panels"]
    panel_index = next((i for i, p in enumerate(panels) if p["id"] == panel_id), None)
    if panel_index is None:
        raise HTTPException(404, f"Unknown panel {panel_id}")
    panel = panels[panel_index]
    candidates = _candidates("panels", panel_id)
    approved = _is_approved("panels", panel_id)
    approved_idx = None
    if approved:
        try:
            approved_bytes = approved.read_bytes()
            for i, c in enumerate(candidates):
                if c.read_bytes() == approved_bytes:
                    approved_idx = i
                    break
        except OSError:
            pass
    prev_id = panels[panel_index - 1]["id"] if panel_index > 0 else None
    next_id = panels[panel_index + 1]["id"] if panel_index < len(panels) - 1 else None
    reference = CLEANED / "panels" / panel_id / "_reference.png"
    return templates.TemplateResponse("panel.html", {
        "request": request,
        "panel": panel,
        "candidates": [c.name for c in candidates],
        "approved_idx": approved_idx,
        "prev_id": prev_id,
        "next_id": next_id,
        "has_reference": reference.exists(),
        "panel_index": panel_index + 1,
        "panel_total": len(panels),
    })


@app.post("/panels/{panel_id}/approve")
def approve_panel(panel_id: str, candidate: str = Form(...)):
    src = CLEANED / "panels" / panel_id / candidate
    if not src.exists():
        raise HTTPException(404, f"No such candidate {candidate}")
    dst = _approved_path("panels", panel_id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return RedirectResponse(f"/panels/{panel_id}", status_code=303)


@app.post("/panels/{panel_id}/unapprove")
def unapprove_panel(panel_id: str):
    dst = _approved_path("panels", panel_id)
    if dst.exists():
        dst.unlink()
    return RedirectResponse(f"/panels/{panel_id}", status_code=303)


@app.get("/centerpiece", response_class=HTMLResponse)
def centerpiece_view(request: Request):
    catalog = _load_catalog()
    cp = catalog["centerpiece"]
    candidates = _candidates("centerpiece")
    approved_path = APPROVED / "centerpiece.png"
    refinements = []
    if REFINEMENTS.exists():
        refinements = sorted(REFINEMENTS.glob("centerpiece_v*.png"))
    return templates.TemplateResponse("centerpiece.html", {
        "request": request,
        "centerpiece": cp,
        "candidates": [c.name for c in candidates],
        "approved": approved_path.exists(),
        "refinements": [r.name for r in refinements],
        "target_size": cp["target_size"],
    })


@app.post("/centerpiece/select")
def centerpiece_select(candidate: str = Form(...), source: str = Form("candidate")):
    """Promote a cleaned candidate or a refinement to the current centerpiece."""
    if source == "candidate":
        src = CLEANED / "centerpiece" / candidate
    elif source == "refinement":
        src = REFINEMENTS / candidate
    else:
        raise HTTPException(400, f"Unknown source {source}")
    if not src.exists():
        raise HTTPException(404, f"No such file {candidate}")
    dst = APPROVED / "centerpiece.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return RedirectResponse("/centerpiece", status_code=303)


@app.post("/centerpiece/unapprove")
def centerpiece_unapprove():
    p = APPROVED / "centerpiece.png"
    if p.exists():
        p.unlink()
    return RedirectResponse("/centerpiece", status_code=303)


@app.post("/centerpiece/refine")
async def centerpiece_refine(
    mask_b64: str = Form(...),
    prompt_hint: str = Form(""),
):
    """Run masked inpainting on the current centerpiece using the provided prompt hint."""
    base = APPROVED / "centerpiece.png"
    if not base.exists():
        return JSONResponse({"error": "No approved centerpiece yet"}, status_code=400)

    catalog = _load_catalog()
    style_prompt = catalog.get("style", {}).get("prompt", "")
    cp_prompt = catalog["centerpiece"].get("prompt", "")
    full_prompt = ". ".join(p for p in [style_prompt, cp_prompt, prompt_hint] if p)

    src_bytes = base.read_bytes()
    mask_bytes = base64.b64decode(mask_b64.split(",", 1)[-1])

    # Normalize mask: ensure it's pure black/white at the source-image dimensions.
    src_img = Image.open(io.BytesIO(src_bytes)).convert("RGBA")
    mask = Image.open(io.BytesIO(mask_bytes)).convert("L").resize(src_img.size, Image.NEAREST)
    mask = mask.point(lambda v: 255 if v > 32 else 0)
    mask_buf = io.BytesIO()
    mask.save(mask_buf, format="PNG")
    mask_bytes = mask_buf.getvalue()

    try:
        result_bytes = _pixellab_inpaint(
            prompt=full_prompt,
            source_image=src_bytes,
            mask_image=mask_bytes,
            palette=_palette_for_provider(),
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    REFINEMENTS.mkdir(parents=True, exist_ok=True)
    n = len(list(REFINEMENTS.glob("centerpiece_v*.png"))) + 1
    out = REFINEMENTS / f"centerpiece_v{n:02d}.png"
    out.write_bytes(result_bytes)
    return JSONResponse({"refinement": out.name, "url": f"/asset/refinements/{out.name}"})


@app.get("/asset/{rest:path}")
def asset(rest: str):
    target = _safe_workspace_path(rest)
    if not target.exists() or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)


# ────────────────── inpainting client (lightweight) ──────────────────


def _pixellab_inpaint(
    prompt: str,
    source_image: bytes,
    mask_image: bytes,
    palette: list[tuple[int, int, int]] | None,
) -> bytes:
    """Direct PixelLab inpaint call. Mirrors pipeline/.../pixellab.py to keep
    the review UI image lean (no pipeline package install needed)."""
    api_key = os.environ.get("PIXELLAB_API_KEY", "").strip()
    provider = os.environ.get("BOARDFACTORY_PROVIDER", "pixellab").lower()

    if provider == "mock" or not api_key:
        # Mock: return source with a slight tint over the masked region.
        src = Image.open(io.BytesIO(source_image)).convert("RGBA")
        mask = Image.open(io.BytesIO(mask_image)).convert("L").resize(src.size)
        tint = Image.new("RGBA", src.size, (255, 80, 30, 100))
        composed = Image.composite(Image.alpha_composite(src, tint), src, mask)
        buf = io.BytesIO()
        composed.save(buf, format="PNG")
        return buf.getvalue()

    body = {
        "description": prompt,
        "image": {"type": "base64", "base64": base64.b64encode(source_image).decode()},
        "mask": {"type": "base64", "base64": base64.b64encode(mask_image).decode()},
    }
    if palette:
        body["forced_palette"] = [list(c) for c in palette]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=120) as client:
        r = client.post("https://api.pixellab.ai/v1/inpaint-image", json=body, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"PixelLab inpaint returned {r.status_code}: {r.text[:200]}")
        data = r.json()
    b64 = data.get("image", {}).get("base64") or data.get("base64")
    if not b64:
        raise RuntimeError(f"PixelLab response missing image data: {data}")
    return base64.b64decode(b64)
