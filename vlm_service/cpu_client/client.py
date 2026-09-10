"""Synchronous OpenAI SDK client for the self-hosted vLLM Chat Completions API."""

import base64
import math
from pathlib import Path
import urllib.parse

from openai import APIConnectionError, APIStatusError, APITimeoutError, DefaultHttpxClient, OpenAI


def image_part(path):
    path = Path(path)
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    media_type = media_types.get(path.suffix.lower())
    if not media_type:
        raise ValueError("use PNG/JPEG/WebP; convert PDF pages or extract text on the CPU first")
    with path.open("rb") as source:
        data = source.read(8 * 1024 * 1024 + 1)
    if not data or len(data) > 8 * 1024 * 1024:
        raise ValueError("image must be non-empty and at most 8 MiB")
    return {"type": "image_url", "image_url": {
        "url": f"data:{media_type};base64," + base64.b64encode(data).decode("ascii")
    }}


class VlmClient:
    def __init__(self, base_url, *, api_key, model="qwen3.5-9b", timeout_seconds=180):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("base_url must be an HTTP(S) API base without credentials, query or fragment")
        if not api_key or "\n" in api_key or "\r" in api_key:
            raise ValueError("set VLM_API_KEY to the GPU service credential")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout_seconds
        self._sdk = OpenAI(
            base_url=self.base_url,
            api_key=api_key,
            timeout=self.timeout,
            # Preserve one attempt per call; retry policy belongs to the CPU application.
            max_retries=0,
            # Keep private documents at the explicit endpoint, without env proxies or redirects.
            http_client=DefaultHttpxClient(trust_env=False, follow_redirects=False),
        )

    def close(self):
        self._sdk.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def chat(self, messages, *, max_tokens=512, thinking=False, tools=None, tool_choice=None):
        if type(max_tokens) is not int or max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        if type(thinking) is not bool:
            raise ValueError("thinking must be boolean")
        payload = {"model": self.model, "messages": messages, "temperature": 0,
                   "max_completion_tokens": max_tokens,
                   "extra_body": {"chat_template_kwargs": {"enable_thinking": thinking}}}
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        try:
            completion = self._sdk.chat.completions.create(**payload)
            # Preserve the examples' dict interface, including vLLM extension fields.
            return completion.model_dump(mode="json", exclude_unset=True)
        except APIStatusError as error:
            # Avoid including credentials or document content in client error logs.
            raise RuntimeError(f"VLM HTTP {error.status_code}; check endpoint, model, token and server log") from None
        except APITimeoutError:
            raise RuntimeError("VLM request timed out; check server load or timeout_seconds") from None
        except APIConnectionError:
            raise RuntimeError("VLM connection failed; check endpoint and network access") from None
