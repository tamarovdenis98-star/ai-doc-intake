# ADR 0002: Originals in S3 (MinIO), addressed by sha256

**Status:** accepted (stage 6)

## Decision
- The original file is stored as `originals/<sha256[:2]>/<sha256>.<ext>`; `documents.sha256` is UNIQUE.
  The same PDF sent twice (or by mail and by Telegram) is one document: the object write is a no-op and the
  insert is `ON CONFLICT DO NOTHING`. The object is written before the row, so a row never points to nothing.
- A re-scan of a known document has different bytes; it is caught later by the business key
  (supplier INN + number + date) in the validator.

## Supply note
Official MinIO container images stopped being published in 2025 (Docker Hub repository denied, quay.io
unauthorized from this VPS). The stack uses `bitnamilegacy/minio:2025.7.23-debian-12-r5` (MinIO built by Bitnami,
archived catalog), pinned. The service talks plain S3 API (`minio` Python client), so Garage / SeaweedFS /
cloud S3 are a configuration change (`S3_ENDPOINT`, keys), not a code change.
