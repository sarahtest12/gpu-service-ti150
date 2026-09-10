"""Synchronous OpenAI SDK client for the self-hosted vLLM Chat Completions API."""

import base64
from contextlib import contextmanager
import json
import math
from pathlib import Path
import ssl
import urllib.parse

import httpx
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, DefaultHttpxClient, OpenAI


@contextmanager
def _api_errors():
    try:
        yield
    except APIStatusError as error:
        raise RuntimeError(f"VLM HTTP {error.status_code}; check endpoint, model, token and server log") from None
    except (APITimeoutError, httpx.TimeoutException):
        raise RuntimeError("VLM request timed out; check server load or timeout_seconds") from None
    except (APIConnectionError, httpx.TransportError):
        raise RuntimeError("VLM connection failed; check endpoint and network access") from None
    except (APIError, json.JSONDecodeError):
        raise RuntimeError("VLM response failed; check server log") from None


def _stream_chunks(stream):
    finished = False
    with _api_errors():
        for chunk in stream:
            if chunk.object != "chat.completion.chunk":
                raise RuntimeError("VLM returned an invalid stream response")
            data = chunk.model_dump(mode="json", exclude_unset=True)
            for choice in data.get("choices", []):
                if choice.get("finish_reason") == "error":
                    raise RuntimeError("VLM response failed; check server log")
                if choice.get("index") == 0 and choice.get("finish_reason"):
                    finished = True
            yield data
        if not finished:
            raise RuntimeError("VLM stream ended before completion; partial output is incomplete")


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
    def __init__(self, base_url, *, api_key, model="qwen3.5-9b", timeout_seconds=180, ca_file=None):
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
        tls_context = ssl.create_default_context(cafile=str(ca_file)) if ca_file is not None else True
        self._sdk = OpenAI(
            base_url=self.base_url,
            api_key=api_key,
            timeout=self.timeout,
            # Preserve one attempt per call; retry policy belongs to the CPU application.
            max_retries=0,
            # Keep private documents at the explicit endpoint, without env proxies or redirects.
            http_client=DefaultHttpxClient(trust_env=False, follow_redirects=False, verify=tls_context),
        )

    def close(self):
        self._sdk.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _payload(self, messages, max_tokens, thinking, tools, tool_choice):
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
        return payload

    def chat(self, messages, *, max_tokens=512, thinking=False, tools=None, tool_choice=None):
        payload = self._payload(messages, max_tokens, thinking, tools, tool_choice)
        with _api_errors():
            completion = self._sdk.chat.completions.create(**payload)
            # Preserve the examples' dict interface, including vLLM extension fields.
            return completion.model_dump(mode="json", exclude_unset=True)

    @contextmanager
    def stream_chat(self, messages, *, max_tokens=512, thinking=False, tools=None, tool_choice=None):
        """Use ``with client.stream_chat(...) as chunks`` and iterate delta dictionaries.

        Exiting the block closes the HTTP response, including on early break.
        Tool arguments are fragments; assemble and validate them on the CPU.
        """
        payload = self._payload(messages, max_tokens, thinking, tools, tool_choice)
        with _api_errors():
            stream = self._sdk.chat.completions.create(
                **payload, stream=True, stream_options={"include_usage": True},
            )
        with stream:
            yield _stream_chunks(stream)
