"""One client for GigaChat, YandexGPT and OpenAI: all three expose an OpenAI-compatible /chat/completions.

Differences are only in auth and in structured-output support:
  gigachat  OAuth (Authorization key -> 30-min access token, cached), JSON requested in the prompt
  yandex    Api-Key header, model gpt://<folder>/<model>, response_format json_schema
  openai    Bearer key, response_format json_schema
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import uuid

import httpx

from .base import LLMError, LLMResult, Provider

TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class OpenAICompatProvider(Provider):
    def __init__(self, name: str, base_url: str, model: str, json_schema_mode: bool):
        self.name, self.base_url, self.model, self.json_schema_mode = name, base_url.rstrip("/"), model, json_schema_mode

    def headers(self) -> dict:
        raise NotImplementedError

    def complete_json(self, task, system, user, schema, max_tokens):
        body = {"model": self.model, "temperature": 0, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if self.json_schema_mode:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": f"docai_{task}", "schema": schema}}
        t0 = time.monotonic()
        try:
            r = httpx.post(f"{self.base_url}/chat/completions", headers=self.headers(), json=body, timeout=TIMEOUT)
        except httpx.HTTPError as e:
            raise LLMError(f"{self.name}: {type(e).__name__}: {e}", retryable=True) from e
        ms = int((time.monotonic() - t0) * 1000)
        if r.status_code != 200:
            raise LLMError(f"{self.name}: HTTP {r.status_code}: {r.text[:300]}", retryable=r.status_code in (429, 500, 502, 503, 504))
        data = r.json()
        content = data["choices"][0]["message"].get("content") or ""
        usage = data.get("usage") or {}
        return LLMResult(parse_json_object(content, self.name), self.name, data.get("model", self.model),
                         int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)), ms, content)


def parse_json_object(text: str, who: str = "llm") -> dict:
    """Takes the first JSON object out of a reply (tolerates ```json fences and prose around it)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            raise LLMError(f"{who}: no JSON object in the answer: {text[:200]!r}")
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise LLMError(f"{who}: invalid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise LLMError(f"{who}: JSON is not an object")
    return obj


class GigaChat(OpenAICompatProvider):
    OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    _lock = threading.Lock()
    _token: tuple[str, float] | None = None

    def __init__(self):
        super().__init__("gigachat", os.environ.get("GIGACHAT_BASE_URL", "https://gigachat.devices.sberbank.ru/api/v1"),
                         os.environ.get("GIGACHAT_MODEL", "GigaChat"), json_schema_mode=False)
        self.auth_key = os.environ.get("GIGACHAT_AUTH_KEY", "")
        self.scope = os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
        if not self.auth_key:
            raise LLMError("gigachat: GIGACHAT_AUTH_KEY is not set")

    def headers(self):
        return {"Authorization": f"Bearer {self._access_token()}", "Accept": "application/json"}

    def _access_token(self) -> str:
        with self._lock:
            tok = GigaChat._token
            if tok and tok[1] - time.time() > 60:
                return tok[0]
            try:
                r = httpx.post(self.OAUTH_URL, data={"scope": self.scope}, timeout=TIMEOUT, headers={
                    "Authorization": f"Basic {self.auth_key}", "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
            except httpx.HTTPError as e:
                raise LLMError(f"gigachat oauth: {e}", retryable=True) from e
            if r.status_code != 200:
                raise LLMError(f"gigachat oauth: HTTP {r.status_code}: {r.text[:200]}", retryable=r.status_code >= 500)
            d = r.json()
            GigaChat._token = (d["access_token"], d["expires_at"] / 1000)  # ms epoch
            return d["access_token"]


class Yandex(OpenAICompatProvider):
    def __init__(self):
        folder = os.environ.get("YANDEX_FOLDER_ID", "")
        key = os.environ.get("YANDEX_API_KEY", "")
        if not (folder and key):
            raise LLMError("yandex: YANDEX_API_KEY / YANDEX_FOLDER_ID are not set")
        model = os.environ.get("YANDEX_MODEL", "yandexgpt/latest")
        super().__init__("yandex", "https://llm.api.cloud.yandex.net/v1", f"gpt://{folder}/{model}", json_schema_mode=True)
        self.key, self.folder = key, folder

    def headers(self):
        return {"Authorization": f"Api-Key {self.key}", "OpenAI-Project": self.folder}


class OpenAI(OpenAICompatProvider):
    def __init__(self):
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise LLMError("openai: OPENAI_API_KEY is not set")
        super().__init__("openai", os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                         os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), json_schema_mode=True)
        self.key = key

    def headers(self):
        return {"Authorization": f"Bearer {self.key}"}


def make(name: str) -> Provider:
    return {"gigachat": GigaChat, "yandex": Yandex, "openai": OpenAI}[name]()


def _b64(client_id: str, secret: str) -> str:  # helper for docs: how the GigaChat "Authorization key" is built
    return base64.b64encode(f"{client_id}:{secret}".encode()).decode()
