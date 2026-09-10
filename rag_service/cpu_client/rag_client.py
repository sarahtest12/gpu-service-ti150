"""CPU-only client for BGE-M3 dense embeddings through the shared gateway."""

import json
import math
import ssl
import urllib.parse

import httpx
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, DefaultHttpxClient, OpenAI


class RagClient:
    def __init__(self, base_url, *, api_key, model="bge-m3", timeout_seconds=60, ca_file=None):
        parsed = urllib.parse.urlsplit(base_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("base_url must be an HTTP(S) API base without credentials, query or fragment")
        if not api_key or "\n" in api_key or "\r" in api_key:
            raise ValueError("set GPU_API_KEY to the shared gateway credential")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite")
        self.model = model
        self._sdk = OpenAI(
            base_url=base_url.rstrip("/"), api_key=api_key, timeout=timeout_seconds, max_retries=0,
            http_client=DefaultHttpxClient(
                trust_env=False, follow_redirects=False,
                verify=ssl.create_default_context(cafile=str(ca_file)) if ca_file is not None else True,
            ),
        )

    def close(self):
        self._sdk.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def embed(self, texts):
        """Return OpenAI-style data/usage; data[i].embedding is a normalized 1024-vector."""
        if isinstance(texts, str):
            texts = [texts]
        if not isinstance(texts, list) or not texts or any(not isinstance(t, str) or not t.strip() for t in texts):
            raise ValueError("input must be a non-empty string or list of non-empty strings")
        try:
            response = self._sdk.embeddings.create(
                model=self.model, input=texts, encoding_format="float",
                extra_body={"use_activation": True},
            )
            data = response.model_dump(mode="json", exclude_unset=True)
        except APIStatusError as error:
            raise RuntimeError(f"RAG HTTP {error.status_code}; check input length, model, token and server log") from None
        except (APITimeoutError, httpx.TimeoutException):
            raise RuntimeError("RAG request timed out; check server load or timeout_seconds") from None
        except (APIConnectionError, httpx.TransportError):
            raise RuntimeError("RAG connection failed; check endpoint and network access") from None
        except (APIError, json.JSONDecodeError):
            raise RuntimeError("RAG response failed; check server log") from None
        items = data.get("data", [])
        if (data.get("object") != "list" or len(items) != len(texts)
                or [item.get("index") for item in items] != list(range(len(texts)))):
            raise RuntimeError("RAG response has missing or misordered embeddings")
        for item in items:
            vector = item.get("embedding")
            if (not isinstance(vector, list) or len(vector) != 1024
                    or any(type(v) not in (float, int) or not math.isfinite(v) for v in vector)):
                raise RuntimeError("RAG response is not a finite 1024-dimensional vector")
        return data
