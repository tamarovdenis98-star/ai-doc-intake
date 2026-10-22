"""HTTP API used by n8n ([DOCAI] workflows) and by eval/. Every endpoint except /health needs X-Extractor-Token."""
from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
from datetime import date

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import config, db, pipeline, storage

app = FastAPI(title="docai extractor", version="1.0")


def auth(x_extractor_token: str = Header(default="")):
    if not config.TOKEN or not hmac.compare_digest(x_extractor_token, config.TOKEN):
        raise HTTPException(403, "invalid X-Extractor-Token")


@app.exception_handler(pipeline.StepError)
def step_error(_, e: pipeline.StepError):
    # 503 = worth retrying (provider rate limit / outage), 422 = will fail again with the same input
    return JSONResponse({"ok": False, "error": str(e), "retryable": e.retryable}, status_code=503 if e.retryable else 422)


@app.exception_handler(pipeline.BudgetExceeded)
def budget_error(_, e: pipeline.BudgetExceeded):
    return JSONResponse({"ok": False, "error": str(e), "retryable": False, "budget_exceeded": True}, status_code=409)


@app.get("/health")
def health():
    db.one("SELECT 1")
    return {"ok": True, "provider": config.LLM_PROVIDER}


@app.post("/ingest", dependencies=[Depends(auth)])
async def ingest(file: UploadFile = File(...), source: str = Form(...), source_ref: str | None = Form(None),
                 sender: str | None = Form(None), filename: str | None = Form(None)):
    data = await file.read()
    name = filename or file.filename or "document"
    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime in ("", "application/octet-stream"):
        mime = mimetypes.guess_type(name)[0] or mime
    if mime not in config.ALLOWED_MIME:
        return JSONResponse({"ok": False, "skipped": True, "reason": f"unsupported type {mime}"}, status_code=415)
    if not data or len(data) > config.MAX_FILE_BYTES:
        return JSONResponse({"ok": False, "skipped": True, "reason": f"size {len(data)} bytes out of range"}, status_code=413)
    sha = hashlib.sha256(data).hexdigest()
    key = storage.key_for(sha, config.ALLOWED_MIME[mime])
    storage.put(key, data, mime)                 # object first: a row never points to a missing object
    row = db.one("""INSERT INTO documents (sha256, source, source_ref, sender, filename, mime, size_bytes, object_key)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (sha256) DO NOTHING RETURNING id""",
                 (sha, source, source_ref, sender, name, mime, len(data), key))
    if row:
        db.execute("INSERT INTO audit_log (doc_id, actor, action, detail) VALUES (%s, 'system', 'received', %s::jsonb)",
                   (row["id"], json.dumps({"source": source, "sender": sender, "filename": name}, ensure_ascii=False)))
        return {"ok": True, "doc_id": row["id"], "sha256": sha, "duplicate": False}
    existing = db.one("SELECT id, status FROM documents WHERE sha256 = %s", (sha,))
    return {"ok": True, "doc_id": existing["id"], "sha256": sha, "duplicate": True, "status": existing["status"]}


class StepIn(BaseModel):
    provider: str | None = None
    today: date | None = None        # for reproducible validation in tests / eval


@app.post("/documents/{doc_id}/text", dependencies=[Depends(auth)])
def text_step(doc_id: int):
    return pipeline.extract_text(doc_id)


@app.post("/documents/{doc_id}/classify", dependencies=[Depends(auth)])
def classify_step(doc_id: int, body: StepIn | None = None):
    return pipeline.classify(doc_id, (body or StepIn()).provider)


@app.post("/documents/{doc_id}/extract", dependencies=[Depends(auth)])
def extract_step(doc_id: int, body: StepIn | None = None):
    return pipeline.extract(doc_id, (body or StepIn()).provider)


@app.post("/documents/{doc_id}/validate", dependencies=[Depends(auth)])
def validate_step(doc_id: int, body: StepIn | None = None):
    return pipeline.validate(doc_id, (body or StepIn()).today)


@app.get("/documents/{doc_id}", dependencies=[Depends(auth)])
def get_document(doc_id: int):
    d = db.one("""SELECT d.id, d.sha256, d.source, d.filename, d.mime, d.status, d.doc_type, d.class_confidence, d.extracted,
                         d.validation, d.decision, d.tokens_in, d.tokens_out, d.cost_rub, t.method AS text_method, t.chars, t.ocr_confidence
                    FROM documents d LEFT JOIN document_text t ON t.doc_id = d.id WHERE d.id = %s""", (doc_id,))
    if not d:
        raise HTTPException(404, "not found")
    return d
