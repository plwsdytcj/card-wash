"""
Card Wash — FastAPI server.

Endpoints:
  POST /api/upload             – upload a PNG/JSON card, get parsed fields + analysis
  POST /api/rewrite            – rewrite selected fields via LLM
  POST /api/apply              – apply rewritten fields and get the final card
  POST /api/export/json        – export current card as JSON download
  POST /api/export/png         – export current card as PNG download
  POST /api/batch/upload       – upload multiple cards at once
  POST /api/batch/rewrite      – rewrite all uploaded batch cards
  POST /api/batch/export       – export all batch cards as a ZIP
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from analyzer import analyse_card
from card_io import (
    extract_avatar_from_png,
    extract_avatar_from_webp,
    read_card,
    write_card_to_json,
    write_card_to_png,
)
from models import CharacterCard
from rewriter import (
    LLMConfig,
    LLMProvider,
    RewriteStrength,
    apply_rewrite,
    rewrite_card,
)

app = FastAPI(title="Card Wash", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory session store (card + original PNG bytes) ──────────────────────

_sessions: dict[str, dict[str, Any]] = {}


# ═══════════════════════════════════════════════════════════════════════════════
#  Upload
# ═══════════════════════════════════════════════════════════════════════════════


@app.post("/api/upload")
async def upload_card(file: UploadFile = File(...)):
    """Upload a character card file; returns parsed data + risk analysis."""
    contents = await file.read()
    filename = file.filename or "card.png"

    try:
        card = read_card(contents, filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse card: {e}")

    # Run analysis
    analysis = analyse_card(card)

    # Extract avatar
    avatar = ""
    fname_lower = filename.lower()
    if fname_lower.endswith(".png"):
        avatar = extract_avatar_from_png(contents)
    elif fname_lower.endswith(".webp"):
        avatar = extract_avatar_from_webp(contents)

    # Store session
    session_id = uuid.uuid4().hex[:12]
    _sessions[session_id] = {
        "card": card,
        "original_png": contents if fname_lower.endswith(".png") else None,
        "avatar": avatar,
        "detected_language": analysis.detected_language,
    }

    return {
        "session_id": session_id,
        "card": card.to_v2_dict(),
        "avatar": avatar,
        "analysis": analysis.to_dict(),
        "rewritable_fields": list(card.get_rewritable_fields().keys()),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Rewrite
# ═══════════════════════════════════════════════════════════════════════════════


@app.post("/api/rewrite")
async def rewrite_card_endpoint(
    session_id: str = Form(...),
    provider: str = Form("openai"),
    api_key: str = Form(...),
    model: str = Form("gpt-4o-mini"),
    base_url: Optional[str] = Form(None),
    strength: str = Form("medium"),
    selected_fields: str = Form(""),  # comma-separated
    temperature: float = Form(0.7),
):
    """Rewrite selected fields of the uploaded card using an LLM."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Upload a card first.")

    card: CharacterCard = session["card"]

    # Parse config
    try:
        llm_provider = LLMProvider(provider)
    except ValueError:
        llm_provider = LLMProvider.OPENAI_COMPATIBLE

    config = LLMConfig(
        provider=llm_provider,
        api_key=api_key,
        model=model,
        base_url=base_url if base_url else None,
        temperature=temperature,
    )

    try:
        strength_enum = RewriteStrength(strength)
    except ValueError:
        strength_enum = RewriteStrength.MEDIUM

    fields_list = (
        [f.strip() for f in selected_fields.split(",") if f.strip()]
        if selected_fields
        else None
    )

    detected_lang = session.get("detected_language", "en")

    try:
        result = await rewrite_card(card, strength_enum, config, fields_list, detected_lang)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM rewrite failed: {e}")

    # Store rewrite result in session
    session["last_rewrite"] = result

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Apply
# ═══════════════════════════════════════════════════════════════════════════════


@app.post("/api/apply")
async def apply_rewrite_endpoint(
    session_id: str = Form(...),
    rewritten_fields: str = Form(...),  # JSON string
):
    """Apply (possibly user-edited) rewritten fields onto the card."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    card: CharacterCard = session["card"]

    try:
        fields = json.loads(rewritten_fields)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON for rewritten_fields.")

    apply_rewrite(card, fields)

    # Re-analyse
    analysis = analyse_card(card)

    return {
        "card": card.to_v2_dict(),
        "analysis": analysis.to_dict(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Export
# ═══════════════════════════════════════════════════════════════════════════════


@app.post("/api/export/json")
async def export_json(session_id: str = Form(...)):
    """Export the current card as a JSON file."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    card: CharacterCard = session["card"]
    json_bytes = write_card_to_json(card)
    name = card.display_name.replace(" ", "_")

    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}_washed.json"'},
    )


@app.post("/api/export/png")
async def export_png(session_id: str = Form(...)):
    """Export the current card as a PNG file (needs original PNG)."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    original_png = session.get("original_png")
    if not original_png:
        raise HTTPException(
            status_code=400,
            detail="No original PNG available. The card was uploaded as JSON.",
        )

    card: CharacterCard = session["card"]
    png_bytes = write_card_to_png(card, original_png)
    name = card.display_name.replace(" ", "_")

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{name}_washed.png"'},
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Batch endpoints
# ═══════════════════════════════════════════════════════════════════════════════

# Batch session: { batch_id -> { items: [ {id, filename, card, original_png, avatar, analysis} ] } }
_batches: dict[str, dict[str, Any]] = {}


@app.post("/api/batch/upload")
async def batch_upload(files: list[UploadFile] = File(...)):
    """Upload multiple card files at once. Returns a batch_id and per-file analysis."""
    batch_id = uuid.uuid4().hex[:12]
    items: list[dict[str, Any]] = []

    for file in files:
        contents = await file.read()
        filename = file.filename or "card.png"
        item_id = uuid.uuid4().hex[:8]

        try:
            card = read_card(contents, filename)
            analysis = analyse_card(card)
            avatar = ""
            fn_lower = filename.lower()
            if fn_lower.endswith(".png"):
                avatar = extract_avatar_from_png(contents)
            elif fn_lower.endswith(".webp"):
                avatar = extract_avatar_from_webp(contents)

            items.append({
                "id": item_id,
                "filename": filename,
                "card": card,
                "original_png": contents if fn_lower.endswith(".png") else None,
                "avatar": avatar,
                "analysis": analysis,
                "status": "ready",
                "error": None,
            })
        except Exception as e:
            items.append({
                "id": item_id,
                "filename": filename,
                "card": None,
                "original_png": None,
                "avatar": "",
                "analysis": None,
                "status": "parse_error",
                "error": str(e),
            })

    _batches[batch_id] = {"items": items}

    return {
        "batch_id": batch_id,
        "total": len(items),
        "items": [
            {
                "id": it["id"],
                "filename": it["filename"],
                "status": it["status"],
                "error": it["error"],
                "card_name": it["card"].display_name if it["card"] else None,
                "avatar": it["avatar"],
                "analysis": it["analysis"].to_dict() if it["analysis"] else None,
                "rewritable_fields": (
                    list(it["card"].get_rewritable_fields().keys())
                    if it["card"]
                    else []
                ),
            }
            for it in items
        ],
    }


@app.post("/api/batch/rewrite")
async def batch_rewrite(
    batch_id: str = Form(...),
    provider: str = Form("openai"),
    api_key: str = Form(...),
    model: str = Form("gpt-4o-mini"),
    base_url: Optional[str] = Form(None),
    strength: str = Form("medium"),
    selected_fields: str = Form(""),
    temperature: float = Form(0.7),
    force: bool = Form(False),
):
    """Rewrite all cards in a batch sequentially."""
    batch = _batches.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")

    try:
        llm_provider = LLMProvider(provider)
    except ValueError:
        llm_provider = LLMProvider.OPENAI_COMPATIBLE

    config = LLMConfig(
        provider=llm_provider,
        api_key=api_key,
        model=model,
        base_url=base_url if base_url else None,
        temperature=temperature,
    )
    try:
        strength_enum = RewriteStrength(strength)
    except ValueError:
        strength_enum = RewriteStrength.MEDIUM

    fields_list = (
        [f.strip() for f in selected_fields.split(",") if f.strip()]
        if selected_fields
        else None
    )

    results = []
    for item in batch["items"]:
        if item["status"] == "parse_error" or item["card"] is None:
            results.append({
                "id": item["id"],
                "filename": item["filename"],
                "status": "skipped",
                "error": item["error"],
                "risk_before": None,
                "risk_after": None,
            })
            continue

        card: CharacterCard = item["card"]
        analysis_before = item["analysis"]
        risk_before = analysis_before.overall_risk if analysis_before else 0

        # Skip cards with no risk (unless force mode)
        if risk_before == 0 and not force:
            results.append({
                "id": item["id"],
                "filename": item["filename"],
                "status": "no_risk",
                "risk_before": 0,
                "risk_after": 0,
                "error": None,
            })
            item["status"] = "done"
            continue

        try:
            item_lang = item["analysis"].detected_language if item["analysis"] else "en"
            rw = await rewrite_card(card, strength_enum, config, fields_list, item_lang)
            if rw["rewritten"]:
                apply_rewrite(card, rw["rewritten"])
            analysis_after = analyse_card(card)
            item["analysis"] = analysis_after
            item["status"] = "done"

            results.append({
                "id": item["id"],
                "filename": item["filename"],
                "status": "ok",
                "risk_before": risk_before,
                "risk_after": analysis_after.overall_risk,
                "fields_rewritten": len(rw.get("rewritten", {})),
                "error": None,
            })
        except Exception as e:
            item["status"] = "rewrite_error"
            item["error"] = str(e)
            results.append({
                "id": item["id"],
                "filename": item["filename"],
                "status": "error",
                "risk_before": risk_before,
                "risk_after": None,
                "error": str(e),
            })

    return {"batch_id": batch_id, "results": results}


@app.post("/api/batch/export")
async def batch_export(
    batch_id: str = Form(...),
    format: str = Form("json"),  # "json" or "png"
):
    """Export all successfully processed batch cards as a ZIP file."""
    batch = _batches.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in batch["items"]:
            if item["card"] is None:
                continue

            card: CharacterCard = item["card"]
            stem = item["filename"].rsplit(".", 1)[0]

            if format == "png" and item["original_png"]:
                out_bytes = write_card_to_png(card, item["original_png"])
                zf.writestr(f"{stem}_washed.png", out_bytes)
            else:
                out_bytes = write_card_to_json(card)
                zf.writestr(f"{stem}_washed.json", out_bytes)

    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="card_wash_batch.zip"'},
    )


# ── Serve frontend ───────────────────────────────────────────────────────────

app.mount("/", StaticFiles(directory="static", html=True), name="static")
