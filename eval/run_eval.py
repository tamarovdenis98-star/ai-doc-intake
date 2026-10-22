#!/usr/bin/env python3
"""Runs the dataset through the extractor service and measures quality, routing, time and cost.

  python eval/run_eval.py --base http://127.0.0.1:58080 --token $EXTRACTOR_TOKEN --provider rules
Writes eval/runs/<provider>.json. Standard library only (runs on any host next to the service).
Metrics:
  classification accuracy; per-field accuracy over the fields present in the ground truth
  (strings: case/space-insensitive, numbers: ±0.01, line items: count and amounts);
  routing: share auto / review, and agreement with the expected decision (defects must go to review);
  time per document (client wall time of all steps) and LLM tokens / cost per document.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import statistics
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIELDS = ["number", "date", "supplier_name", "supplier_inn", "supplier_kpp", "buyer_name", "buyer_inn", "buyer_kpp",
          "total_without_vat", "vat_rate", "vat_amount", "total", "supplier_account", "supplier_bik", "upd_status",
          "subject", "valid_until"]


class Api:
    def __init__(self, base, token):
        self.base, self.token = base.rstrip("/"), token

    def _req(self, method, path, body=None, headers=None, timeout=300):
        req = urllib.request.Request(self.base + path, data=body, method=method,
                                     headers={"X-Extractor-Token": self.token, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def post_json(self, path, obj=None):
        return self._req("POST", path, json.dumps(obj or {}).encode(), {"Content-Type": "application/json"})

    def ingest(self, path: Path, mime: str):
        b = uuid.uuid4().hex
        parts = []
        for name, val in (("source", "api"), ("source_ref", f"eval:{path.name}"), ("filename", path.name)):
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
                     + path.read_bytes() + f"\r\n--{b}--\r\n".encode())
        return self._req("POST", "/ingest", b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={b}"})


def norm(v):
    if isinstance(v, str):
        return re.sub(r"\s+", " ", v.replace("«", '"').replace("»", '"').strip().lower())
    return v


def same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(float(a) - float(b)) <= 0.011
    return norm(a) == norm(b)


def run(args):
    api = Api(args.base, args.token)
    manifest = json.loads((Path(args.dataset) / "manifest.json").read_text(encoding="utf-8"))
    docs = manifest["documents"][: args.limit or None]
    today = manifest["today"]
    rows = []
    for m in docs:
        path = Path(args.dataset) / m["file"]
        t0 = time.perf_counter()
        st, ing = api.ingest(path, m["mime"] or mimetypes.guess_type(path.name)[0])
        if st != 200:
            rows.append({"id": m["id"], "error": f"ingest {st}: {ing}"})
            continue
        did = ing["doc_id"]
        steps, err = {}, None
        for step, body in (("text", None), ("classify", {"provider": args.provider}), ("extract", {"provider": args.provider}),
                           ("validate", {"today": today})):
            ts = time.perf_counter()
            st, res = api.post_json(f"/documents/{did}/{step}", body)
            steps[step] = round(time.perf_counter() - ts, 2)
            if st != 200:
                err = f"{step} {st}: {res.get('error', res)}"
                break
        st, doc = api._req("GET", f"/documents/{did}")
        elapsed = round(time.perf_counter() - t0, 2)
        exp = m["expected"]
        got = doc.get("extracted") or {}
        fields = {f: same(got.get(f), exp.get(f)) for f in FIELDS if f in exp}
        lines_ok = None
        if "lines" in exp:
            gl = got.get("lines") or []
            lines_ok = len(gl) == len(exp["lines"]) and all(same(a.get("amount"), b["amount"]) for a, b in zip(gl, exp["lines"]))
        rows.append({
            "id": m["id"], "file": m["file"], "doc_id": did, "scan": m["scan"], "defect": m["defect"],
            "expected_type": m["doc_type"], "type": doc.get("doc_type"), "class_confidence": float(doc.get("class_confidence") or 0),
            "text_method": doc.get("text_method"), "ocr_confidence": float(doc["ocr_confidence"]) if doc.get("ocr_confidence") is not None else None,
            "fields": fields, "lines_ok": lines_ok,
            "expected_decision": m["expected_decision"], "decision": doc.get("decision"),
            "failed_checks": [c["code"] for c in ((doc.get("validation") or {}).get("checks") or []) if not c["ok"]],
            "tokens": int(doc.get("tokens_in") or 0) + int(doc.get("tokens_out") or 0), "cost_rub": float(doc.get("cost_rub") or 0),
            "seconds": elapsed, "steps": steps, "error": err,
        })
        print(f"{m['id']:3d} {m['doc_type']:8s} -> {str(doc.get('doc_type')):8s} {doc.get('decision')!s:6s} "
              f"(exp {m['expected_decision']}) fields {sum(fields.values())}/{len(fields)} {elapsed:5.1f}s {err or ''}", flush=True)
    summary = summarize(rows, args.provider)
    out = ROOT / "runs" / f"{args.provider}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "documents": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"written {out}")


def summarize(rows, provider):
    ok = [r for r in rows if not r.get("error")]
    per_field = {}
    for f in FIELDS:
        vals = [r["fields"][f] for r in ok if f in r["fields"]]
        if vals:
            per_field[f] = {"accuracy": round(sum(vals) / len(vals), 3), "n": len(vals)}
    lines = [r["lines_ok"] for r in ok if r["lines_ok"] is not None]
    secs = [r["seconds"] for r in ok]
    pct = lambda xs, p: sorted(xs)[min(len(xs) - 1, int(round(p * (len(xs) - 1))))] if xs else None  # noqa: E731
    defects = [r for r in ok if r["defect"]]
    clean = [r for r in ok if r["expected_decision"] == "auto"]
    return {
        "provider": provider, "documents": len(rows), "errors": len(rows) - len(ok),
        "classification_accuracy": round(sum(r["type"] == r["expected_type"] for r in ok) / len(ok), 3) if ok else None,
        "field_accuracy_overall": round(sum(sum(r["fields"].values()) for r in ok) / max(1, sum(len(r["fields"]) for r in ok)), 3),
        "per_field": per_field,
        "line_items_exact": round(sum(lines) / len(lines), 3) if lines else None,
        "auto_share": round(sum(r["decision"] == "auto" for r in ok) / len(ok), 3) if ok else None,
        "review_share": round(sum(r["decision"] == "review" for r in ok) / len(ok), 3) if ok else None,
        "defects_caught": f"{sum(r['decision'] == 'review' for r in defects)}/{len(defects)}",
        "clean_auto": f"{sum(r['decision'] == 'auto' for r in clean)}/{len(clean)}",
        "wrong_auto": sum(r["decision"] == "auto" and r["expected_decision"] == "review" for r in ok),
        "seconds_per_doc": {"mean": round(statistics.mean(secs), 2), "p95": pct(secs, .95)} if secs else None,
        "seconds_scan_mean": round(statistics.mean([r["seconds"] for r in ok if r["scan"]]), 2) if any(r["scan"] for r in ok) else None,
        "tokens_per_doc": round(statistics.mean([r["tokens"] for r in ok]), 1) if ok else None,
        "cost_rub_per_doc": round(statistics.mean([r["cost_rub"] for r in ok]), 4) if ok else None,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("EXTRACTOR_URL", "http://127.0.0.1:58080"))
    ap.add_argument("--token", default=os.environ.get("EXTRACTOR_TOKEN", ""))
    ap.add_argument("--provider", default="rules")
    ap.add_argument("--dataset", default=str(ROOT / "dataset"))
    ap.add_argument("--limit", type=int, default=0)
    run(ap.parse_args())
