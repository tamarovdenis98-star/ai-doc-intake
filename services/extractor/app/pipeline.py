"""Steps called by n8n: text, classify, extract, validate. Each step reads and writes Postgres, so n8n only
passes a document id and the service is safe to call again (every step overwrites its own result)."""
from __future__ import annotations

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from . import config, db, mask, prompts, storage, text, validate as validator
from .llm import LLMError, get_provider


class BudgetExceeded(Exception):
    pass


class StepError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@lru_cache
def schema(name: str) -> dict:
    return json.loads((Path(config.SCHEMAS_DIR) / f"{name}.schema.json").read_text(encoding="utf-8"))


def schema_errors(obj: dict, name: str) -> list[str]:
    return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in Draft202012Validator(schema(name)).iter_errors(obj)]


# ------------------------------------------------------------------ text
def extract_text(doc_id: int) -> dict:
    doc = db.one("SELECT id, mime, object_key FROM documents WHERE id = %s", (doc_id,))
    if not doc:
        raise StepError(f"document {doc_id} not found")
    res = text.extract(storage.get(doc["object_key"]), doc["mime"])
    # a new processing pass starts here: the per-document LLM budget applies to this pass
    # (the full history stays in llm_calls)
    db.execute("UPDATE documents SET tokens_in = 0, tokens_out = 0, cost_rub = 0, updated_at = now() WHERE id = %s", (doc_id,))
    db.execute("""INSERT INTO document_text (doc_id, method, pages, chars, ocr_confidence, text) VALUES (%s, %s, %s, %s, %s, %s)
                  ON CONFLICT (doc_id) DO UPDATE SET method = EXCLUDED.method, pages = EXCLUDED.pages, chars = EXCLUDED.chars,
                  ocr_confidence = EXCLUDED.ocr_confidence, text = EXCLUDED.text, extracted_at = now()""",
               (doc_id, res.method, res.pages, len(res.text), res.ocr_confidence, res.text))
    return {"doc_id": doc_id, "method": res.method, "pages": res.pages, "chars": len(res.text), "ocr_confidence": res.ocr_confidence}


# ------------------------------------------------------------------ LLM steps
def _budget(doc_id: int) -> tuple[int, float]:
    """Remaining (tokens, rub) for this document."""
    s = db.settings()
    used = db.one("SELECT tokens_in + tokens_out AS t, cost_rub AS c FROM documents WHERE id = %s", (doc_id,))
    left_t = int(s.get("llm_max_tokens_per_doc", 24000)) - int(used["t"])
    left_c = float(s.get("llm_max_cost_rub_per_doc", 3)) - float(used["c"])
    if left_t <= 0 or left_c <= 0:
        raise BudgetExceeded(f"LLM budget of document {doc_id} is spent (tokens left {left_t}, rub left {left_c:.2f})")
    return left_t, left_c


def _call(doc_id: int, provider_name: str, task: str, system: str, user: str, sch: dict, max_tokens: int):
    left_t, _ = _budget(doc_id)
    provider = get_provider(provider_name)
    leak = mask.leaked(user.split("<<<DOCUMENT>>>", 1)[-1])
    if leak and provider.name != "rules":   # never send unmasked personal data out
        raise StepError(f"refusing to send unmasked personal data ({len(leak)} matches)")
    try:
        res = provider.complete_json(task, system, user, sch, min(max_tokens, left_t))
    except LLMError as e:
        db.execute("INSERT INTO llm_calls (doc_id, provider, model, task, ok, error) VALUES (%s, %s, %s, %s, false, %s)",
                   (doc_id, provider.name, provider.model, task, str(e)[:500]))
        raise StepError(str(e), retryable=e.retryable) from e
    cost = round(res.tokens_in / 1000 * config.PRICE_IN_PER_1K + res.tokens_out / 1000 * config.PRICE_OUT_PER_1K, 4)
    db.execute("""INSERT INTO llm_calls (doc_id, provider, model, task, tokens_in, tokens_out, cost_rub, duration_ms, ok)
                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)""",
               (doc_id, res.provider, res.model, task, res.tokens_in, res.tokens_out, cost, res.duration_ms))
    db.execute("UPDATE documents SET tokens_in = tokens_in + %s, tokens_out = tokens_out + %s, cost_rub = cost_rub + %s, updated_at = now() WHERE id = %s",
               (res.tokens_in, res.tokens_out, cost, doc_id))
    return res


def _doc_text(doc_id: int) -> str:
    row = db.one("SELECT text FROM document_text WHERE doc_id = %s", (doc_id,))
    if not row:
        raise StepError(f"document {doc_id} has no text yet: call /text first")
    return row["text"]


def classify(doc_id: int, provider: str | None = None) -> dict:
    provider = provider or config.LLM_PROVIDER
    masked, _ = mask.mask(_doc_text(doc_id)[: config.CLASSIFY_MAX_CHARS])
    system, user = prompts.classify_messages(masked)
    res = _call(doc_id, provider, "classify", system, user, schema("classification"), 300)
    errs = schema_errors(res.content, "classification")
    if errs:
        raise StepError(f"classification answer does not match the schema: {errs[:3]}", retryable=True)
    c = res.content
    db.execute("UPDATE documents SET doc_type = %s, class_confidence = %s, updated_at = now() WHERE id = %s",
               (c["doc_type"], round(float(c["confidence"]), 3), doc_id))
    return {"doc_id": doc_id, **c, "provider": res.provider, "model": res.model, "tokens": res.tokens_in + res.tokens_out}


def extract(doc_id: int, provider: str | None = None) -> dict:
    provider = provider or config.LLM_PROVIDER
    doc = db.one("SELECT doc_type FROM documents WHERE id = %s", (doc_id,))
    if not doc or not doc["doc_type"]:
        raise StepError(f"document {doc_id} is not classified yet")
    if doc["doc_type"] == "other":
        return {"doc_id": doc_id, "skipped": True, "reason": "doc_type other"}
    dtype = doc["doc_type"]
    sch = schema(dtype)
    masked, mapping = mask.mask(_doc_text(doc_id)[: config.EXTRACT_MAX_CHARS])
    system, user = prompts.extract_messages(dtype, sch, masked)
    res = _call(doc_id, provider, "extract", system, user, sch, 2500)
    data = normalize(res.content, sch)
    errs = schema_errors(data, dtype)
    if errs and provider != "rules":
        system, user = prompts.repair_messages(dtype, sch, masked, data, errs)
        res = _call(doc_id, provider, "repair", system, user, sch, 2500)
        data = normalize(res.content, sch)
        errs = schema_errors(data, dtype)
    data = mask.unmask(data, mapping)
    db.execute("UPDATE documents SET extracted = %s, updated_at = now() WHERE id = %s", (json.dumps(data, ensure_ascii=False), doc_id))
    return {"doc_id": doc_id, "doc_type": dtype, "data": data, "schema_errors": errs, "provider": res.provider}


def normalize(obj: dict, sch: dict) -> dict:
    """Light, safe clean-up of model output: drops unknown keys, strips spaces in identifiers, coerces numbers."""
    props = sch["properties"]
    out = {k: obj.get(k) for k in props}
    for k in ("supplier_inn", "buyer_inn", "supplier_kpp", "buyer_kpp", "supplier_account", "supplier_bik"):
        if k in out and isinstance(out[k], str):
            v = re.sub(r"\s", "", out[k])
            out[k] = v or None
    for k in ("total_without_vat", "vat_amount", "total"):
        if k in out and isinstance(out[k], str):
            out[k] = _num(out[k])
    if "vat_rate" in out and isinstance(out["vat_rate"], (str, float)):
        n = _num(str(out["vat_rate"]).replace("%", ""))
        out["vat_rate"] = int(n) if n is not None else None
    if isinstance(out.get("lines"), list):
        lines = []
        for ln in out["lines"]:
            if isinstance(ln, dict):
                ln = {k: ln.get(k) for k in ("name", "qty", "unit", "price", "amount")}
                for k in ("qty", "price", "amount"):
                    if isinstance(ln[k], str):
                        ln[k] = _num(ln[k])
                lines.append(ln)
        out["lines"] = lines
    return out


def _num(s: str):
    s = re.sub(r"[^\d,.\-]", "", s).replace(",", ".")
    if s.count(".") > 1:
        head, _, tail = s.rpartition(".")
        s = head.replace(".", "") + "." + tail
    try:
        return float(s)
    except ValueError:
        return None


# ------------------------------------------------------------------ validation
def validate(doc_id: int, today: date | None = None) -> dict:
    doc = db.one("SELECT doc_type, class_confidence, extracted FROM documents WHERE id = %s", (doc_id,))
    if not doc or not doc["doc_type"]:
        raise StepError(f"document {doc_id} is not classified yet")
    data = doc["extracted"] or {}
    dup = None
    if data.get("supplier_inn") and data.get("number") and data.get("date"):
        row = db.one("""SELECT id FROM documents WHERE id < %s AND status NOT IN ('rejected', 'skipped')
                        AND extracted->>'supplier_inn' = %s AND extracted->>'number' = %s AND extracted->>'date' = %s
                        ORDER BY id LIMIT 1""", (doc_id, data["supplier_inn"], data["number"], data["date"]))
        dup = row["id"] if row else None
    s = db.settings()
    required = schema(doc["doc_type"])["required"] if doc["doc_type"] != "other" else []
    res = validator.validate(doc["doc_type"], data, today=today, duplicate_of=dup,
                             class_confidence=float(doc["class_confidence"]) if doc["class_confidence"] is not None else None,
                             min_class_confidence=float(s.get("auto_min_class_conf", 0.8)), required=required)
    db.execute("UPDATE documents SET validation = %s, decision = %s, updated_at = now() WHERE id = %s",
               (json.dumps(res, ensure_ascii=False), res["decision"], doc_id))
    return {"doc_id": doc_id, **res}
