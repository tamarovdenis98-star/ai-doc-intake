# ADR 0001: Python service for documents, n8n for orchestration

**Status:** accepted (stage 6)

## Decision
- `services/extractor` (FastAPI) does everything that touches file bytes or needs libraries: hashing and storing
  originals (S3), text extraction (pdfplumber / tesseract), personal-data masking, LLM calls with schema
  validation, and the deterministic validator. Every step reads and writes Postgres by document id, so a step
  can be repeated safely.
- n8n decides *when* and *what next*: polling with `SKIP LOCKED` and a cap on documents in flight (3: OCR is
  CPU-heavy on 1 vCPU), retries with backoff, routing (auto / review), Telegram, accounting system, Bitrix24.
- Files never pass through n8n memory after intake: n8n hands over a document id.

## Why
- n8n Code nodes have no pdf/OCR libraries and must not hold credentials for providers; a service is testable
  with pytest and reusable by `eval/run_eval.py` (the eval measures exactly the code that runs in production).
- n8n ran out of memory under load in project 1 when many executions carried data; ids keep executions small.

## Measured (stage 6)
56 synthetic documents through `[DOCAI] 02 process` → 56 successful executions, 0 errors, 359 s total
(3 in flight, ≈6.4 s per document; scans ≈7.3 s due to OCR).
