"""Settings from the environment (the container gets the stack's .env)."""
import os

PG_DSN = os.environ.get("PG_DSN", "")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "minio:9000")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "docai-originals")
S3_SECURE = os.environ.get("S3_SECURE", "false").lower() == "true"
TOKEN = os.environ.get("EXTRACTOR_TOKEN", "")
MAX_FILE_BYTES = int(float(os.environ.get("MAX_FILE_MB", "15")) * 1024 * 1024)
SCHEMAS_DIR = os.environ.get("SCHEMAS_DIR", "/app/schemas")

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "rules")
PRICE_IN_PER_1K = float(os.environ.get("LLM_PRICE_IN_PER_1K", "0") or 0)
PRICE_OUT_PER_1K = float(os.environ.get("LLM_PRICE_OUT_PER_1K", "0") or 0)

# Text sent to an external LLM is cut: classification needs the header, extraction the whole document.
CLASSIFY_MAX_CHARS = 4000
EXTRACT_MAX_CHARS = 14000

ALLOWED_MIME = {
    "application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/tiff": "tif", "image/webp": "webp",
}
