# Fun-CosyVoice3 Bi-Streaming TTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the public CosyVoice v1 HTTP API with an authenticated, reusable WebSocket that streams text into `Fun-CosyVoice3-0.5B-2512` while streaming 24 kHz PCM audio out.

**Architecture:** FastAPI owns the WebSocket state machine while a bounded `TextStream` bridges async client messages to CosyVoice's synchronous text `Generator`. A single CoreX worker invokes native PyTorch `inference_zero_shot(..., stream=True)` using one cached AISHELL-3 voice; NGINX authenticates the public handshake and proxies it to the loopback service.

**Tech Stack:** Python 3.10, FastAPI/Starlette WebSocket, CoreX torch/torchaudio 2.7.1, CosyVoice3 native PyTorch, CPU ONNX Runtime, NGINX 1.30, `websockets` sync CPU client, `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-17-cosyvoice3-bistreaming-tts-design.md`

## Global Constraints

- Model is `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` standard `llm.pt`; do not load `llm.rl.pt`.
- Set `load_vllm=False` and `load_trt=False`; do not install CUDA, TensorRT, vLLM, or `onnxruntime-gpu`.
- Run PyTorch on GPU 0 and the speech tokenizer with ONNX Runtime `CPUExecutionProvider`.
- Public TTS business API is only `WSS /tts/v1/realtime`; remove public speech, voices, and TTS health HTTP routes.
- Audio is PCM S16LE, 24 kHz, mono. One WebSocket session and one utterance may generate at a time.
- Fixed public voice ID is `aishell3-female`; every utterance reuses the same cached prompt.
- Preserve internal authenticated `GET /health` and `GET /metrics` on `127.0.0.1:8004`.
- Never log input text, prompt text, audio, credentials, filesystem prompt paths, or stack traces in client errors.
- Preserve unrelated uncommitted files and existing algorithm services.

---

### Task 1: Text stream and CosyVoice3 engine

**Files:**
- Create: `tts_service/scripts/engine.py`
- Create: `tts_service/tests/test_engine.py`

**Interfaces:**
- Produces `TextStream(max_chunks: int)` with `append(text: str)`, `finish()`, `cancel()`, and iterator behavior.
- Produces `CosyVoice3Engine(model, cfg)` with `acquire() -> bool`, `release() -> None`, and `synthesize(text_stream, request_id: str, utterance_id: str) -> Iterator[bytes]`.
- `model.inference_zero_shot` receives the `TextStream`, configured prompt text/path, `zero_shot_spk_id="aishell3-female"`, `stream=True`, and `speed=1.0`.

- [ ] **Step 1: Write failing stream and engine tests**

```python
def test_text_stream_delivers_appends_until_finish(self):
    stream = TextStream(max_chunks=2)
    stream.append("第一段")
    stream.append("第二段")
    stream.finish()
    self.assertEqual(list(stream), ["第一段", "第二段"])

def test_engine_uses_cached_voice_and_streams_pcm(self):
    stream = TextStream(max_chunks=2)
    stream.append("测试")
    stream.finish()
    chunks = list(self.engine.synthesize(stream, "req", "utt"))
    self.assertEqual(np.frombuffer(b"".join(chunks), dtype="<i2").tolist(), [-32767, 0, 32767])
    self.assertEqual(self.model.calls[0][3:], ("aishell3-female", True, 1.0))
```

Also test bounded queue overflow, duplicate finish, cancel unblocking an iterator, one-slot concurrency, empty tensor suppression, generator cleanup, and one TTFT observation per utterance.

- [ ] **Step 2: Run tests and confirm RED**

Run: `tts_service/.venv/bin/python -m unittest tts_service.tests.test_engine -v`

Expected: import failure because `tts_service/scripts/engine.py` does not exist.

- [ ] **Step 3: Implement the bounded bridge and engine**

```python
class TextStream:
    EOF = object()

    def __init__(self, max_chunks):
        self._queue = queue.Queue(maxsize=max_chunks)
        self._closed = threading.Event()

    def append(self, text):
        if self._closed.is_set():
            raise StreamClosed("text stream is closed")
        self._queue.put_nowait(text)

    def finish(self):
        if not self._closed.is_set():
            self._closed.set()
            self._queue.put(self.EOF)

    def __iter__(self):
        while True:
            item = self._queue.get()
            if item is self.EOF:
                return
            yield item
```

Implement cancellation without deadlocking a full queue, PCM clipping/rounding identical to the current service, prompt reuse, generator draining/closing, semaphore ownership, payload-safe logging, and TTFT instrumentation around `model.model.llm.inference_bistream`.

- [ ] **Step 4: Run engine tests and confirm GREEN**

Run: `tts_service/.venv/bin/python -m unittest tts_service.tests.test_engine -v`

Expected: all engine tests pass with no GPU dependency.

- [ ] **Step 5: Commit**

```bash
git add tts_service/scripts/engine.py tts_service/tests/test_engine.py
git commit -m "feat: add CosyVoice3 streaming engine"
```

### Task 2: Reusable WebSocket session

**Files:**
- Modify: `tts_service/scripts/server.py`
- Replace: `tts_service/tests/test_server.py`

**Interfaces:**
- Consumes `TextStream` and `CosyVoice3Engine` from Task 1.
- Produces `create_app(engine, cfg, token) -> FastAPI` with internal `/health`, `/metrics`, and WebSocket `/realtime`.
- Produces event names `session.created`, `input.text`, `input.done`, `session.close`, `audio.start`, `audio.done`, and `error` exactly as the spec.

- [ ] **Step 1: Write failing WebSocket tests**

```python
def test_streams_audio_before_input_done_and_reuses_connection(self):
    with self.client.websocket_connect("/realtime", headers=self.headers) as ws:
        self.assertEqual(ws.receive_json()["type"], "session.created")
        ws.send_json({"type": "input.text", "text": "第一段足够长的文本。"})
        self.assertEqual(ws.receive_json()["type"], "audio.start")
        self.assertTrue(ws.receive_bytes())
        ws.send_json({"type": "input.done"})
        self.assertEqual(ws.receive_json()["type"], "audio.done")
        ws.send_json({"type": "input.text", "text": "第二段文本。"})
        ws.send_json({"type": "input.done"})
        self.assertEqual(ws.receive_json()["type"], "audio.start")
```

Add tests for bad auth, fixed metadata, invalid JSON/type/state, blank/control-sequence text, 1024-character chunk limit, 4096-character utterance limit, duplicate done, session close, connection concurrency, disconnect cleanup, model exception fatal error, and no HTTP `/v1/audio/speech` or `/v1/audio/voices`.

- [ ] **Step 2: Run tests and confirm RED**

Run: `tts_service/.venv/bin/python -m unittest tts_service.tests.test_server -v`

Expected: WebSocket `/realtime` is missing and old HTTP assertions fail against the new contract.

- [ ] **Step 3: Implement the session state machine**

```python
@app.websocket("/realtime")
async def realtime(websocket: WebSocket):
    if not authorized(websocket.headers.get("authorization"), token):
        await websocket.close(code=1008, reason="unauthorized")
        return
    if not engine.acquire():
        await websocket.close(code=1013, reason="TTS concurrency limit reached")
        return
    await websocket.accept()
    await websocket.send_json(session_created())
    try:
        await serve_session(websocket, engine, cfg)
    finally:
        engine.release()
```

Use one pending receive task and one pending engine-output task during an utterance, so text input and PCM output progress concurrently. Keep all WebSocket sends in the session coroutine, apply the 300-second active-input timeout, reject text after `input.done` until `audio.done`, and reset to idle after each successful utterance.

- [ ] **Step 4: Run server and engine tests and confirm GREEN**

Run: `tts_service/.venv/bin/python -m unittest discover -s tts_service/tests -p 'test_*.py' -v`

Expected: all TTS CPU tests pass.

- [ ] **Step 5: Commit**

```bash
git add tts_service/scripts/server.py tts_service/tests/test_server.py
git commit -m "feat: expose reusable TTS WebSocket sessions"
```

### Task 3: Pin CosyVoice3, CoreX provider patch, and AISHELL-3 voice

**Files:**
- Create: `tts_service/assets/voices/aishell3-female.json`
- Create: `tts_service/patches/corex-onnx-provider.patch`
- Modify: `tts_service/config/server.json`
- Modify: `tts_service/scripts/bootstrap.sh`
- Modify: `tts_service/scripts/service.py`
- Modify: `tts_service/.gitignore`
- Create: `tts_service/tests/test_service.py`

**Interfaces:**
- `config()` returns the validated CosyVoice3 configuration with model/source/prompt paths, fixed model and voice IDs, limits, and checksum maps.
- `environment(cfg)` builds the isolated CoreX environment without upstream GPU runtimes.
- `prepare_voice(cfg)` downloads pinned AISHELL-3 files, converts them to the manifest's 24 kHz PCM output, and validates both source and derived SHA-256.
- `load_engine(cfg)` constructs `AutoModel(..., load_vllm=False, load_trt=False, fp16=cfg["fp16"])`, registers `aishell3-female`, and returns `CosyVoice3Engine`.

- [ ] **Step 1: Select and pin the voice asset**

Use the official `AISHELL/AISHELL-3` dataset repository at a full commit revision. Select a female speaker from `spk_info.txt`, choose 5–10 seconds of clean same-speaker audio with exact entries from `content.txt`, inspect it locally, and write a manifest containing dataset revision, speaker ID, utterance paths, transcript, Apache-2.0 URL, source hashes, derived hash, sample rate, channels, and duration.

- [ ] **Step 2: Write failing service validation tests**

```python
def test_config_requires_cosyvoice3_native_bistreaming(self):
    cfg = service.config()
    self.assertEqual(cfg["model_name"], "fun-cosyvoice3-0.5b-2512")
    self.assertFalse(cfg["load_vllm"])
    self.assertFalse(cfg["load_trt"])
    self.assertEqual(cfg["sample_rate_hz"], 24000)
    self.assertEqual(cfg["voice_id"], "aishell3-female")
```

Test rejection of the old model, 22050 Hz, enabled vLLM/TRT, non-loopback listen, missing source/model/voice files, mismatched checksums, unavailable CPU ONNX provider, and unexpected CoreX package versions.

- [ ] **Step 3: Run tests and confirm RED**

Run: `tts_service/.venv/bin/python -m unittest tts_service.tests.test_service -v`

Expected: current v1 configuration violates CosyVoice3 assertions.

- [ ] **Step 4: Implement pinned provisioning and checks**

Update bootstrap to fetch the exact official CosyVoice commit and Hugging Face model snapshot without following floating branches at service startup. Apply `corex-onnx-provider.patch` with `git apply --check` before applying it. Install only pinned frontend dependencies with `--no-deps` where an upstream package would replace torch/torchaudio/onnxruntime. Validate the voice manifest before service launch.

- [ ] **Step 5: Run service tests and environment check**

Run:

```bash
tts_service/.venv/bin/python -m unittest tts_service.tests.test_service -v
tts_service/.venv/bin/python tts_service/scripts/service.py check
```

Expected: unit tests pass; the environment check either passes or reports one concrete missing provisioned artifact before bootstrap is executed.

- [ ] **Step 6: Commit**

```bash
git add tts_service/assets tts_service/patches tts_service/config/server.json \
  tts_service/scripts/bootstrap.sh tts_service/scripts/service.py tts_service/.gitignore \
  tts_service/tests/test_service.py
git commit -m "build: pin CosyVoice3 and AISHELL-3 voice"
```

### Task 4: Gateway WebSocket-only TTS route

**Files:**
- Modify: `gateway/config/server.json`
- Modify: `gateway/configuration.py`
- Modify: `gateway/tests/test_gateway.py`

**Interfaces:**
- Consumes loopback TTS `/realtime` and its internal bearer key.
- Produces public `WSS /tts/v1/realtime` with one connection, 16 KiB message size, 3600-second read/send timeout, buffering disabled, and internal Authorization replacement.

- [ ] **Step 1: Replace the TTS fixture and write failing gateway tests**

Add a TTS WebSocket fixture that records handshake headers, sends `session.created`, echoes an `audio.start` JSON frame plus binary PCM, accepts `input.done`, and sends `audio.done`.

```python
def test_tts_websocket_uses_own_key_and_streams_binary(self):
    with websocket_connect(self.ws_url("/tts/v1/realtime"), additional_headers=self.auth,
                           ssl=self.ssl_context) as ws:
        self.assertEqual(json.loads(ws.recv())["type"], "session.created")
        ws.send(json.dumps({"type": "input.text", "text": "测试"}))
        self.assertEqual(json.loads(ws.recv())["type"], "audio.start")
        self.assertIsInstance(ws.recv(), bytes)
    self.assertEqual(self.tts_headers[0]["authorization"], "Bearer " + self.tts_key)
```

Assert `/tts/v1/audio/speech`, `/tts/v1/audio/voices`, and `/tts/health/ready` return 404; invalid public key returns 401; a second TTS connection returns 429.

- [ ] **Step 2: Run gateway tests and confirm RED**

Run: `source yolov5v70-service/scripts/corex_env.sh && python -m unittest gateway.tests.test_gateway.GatewayTest.test_tts_websocket_uses_own_key_and_streams_binary -v`

Expected: `/tts/v1/realtime` returns 404 because only HTTP TTS locations exist.

- [ ] **Step 3: Render only the TTS WebSocket location**

```nginx
location = /tts/v1/realtime {
    limit_except GET { deny all; }
    limit_conn tts_slots 1;
    proxy_set_header Authorization "Bearer <internal-key>";
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_buffering off;
    proxy_pass http://127.0.0.1:8004/realtime;
}
```

Remove the three old public TTS locations and obsolete TTS HTTP body-size validation.

- [ ] **Step 4: Run complete gateway unit tests**

Run: `source yolov5v70-service/scripts/corex_env.sh && python -m unittest discover -s gateway/tests -p test_gateway.py -v`

Expected: all gateway tests pass.

- [ ] **Step 5: Commit**

```bash
git add gateway/config/server.json gateway/configuration.py gateway/tests/test_gateway.py
git commit -m "feat: proxy TTS bi-streaming WebSocket"
```

### Task 5: CPU WebSocket client

**Files:**
- Replace: `tts_service/cpu_client/tts_client.py`
- Modify: `tts_service/cpu_client/requirements.txt`
- Modify: `tts_service/cpu_client/demo.py`
- Modify: `tts_service/cpu_client/README.md`
- Create: `tts_service/tests/test_cpu_client.py`

**Interfaces:**
- Produces `TtsRealtimeClient(base_url, api_key, timeout_seconds=3600, ca_file=None)`.
- `connect()` opens `/tts/v1/realtime` once and validates `session.created`.
- `synthesize(text_chunks: Iterable[str]) -> Iterator[bytes]` sends chunks, sends `input.done`, and yields PCM until `audio.done`; repeated calls reuse the socket.
- `close()` sends `session.close` when idle and closes transport.

- [ ] **Step 1: Write failing client protocol tests**

Use a local `websockets.sync.server` fixture and assert Authorization, path, chunk ordering, `input.done`, binary-only audio between start/done, metadata validation, repeated synthesis on one connection, server error propagation, timeout handling, and clean close.

- [ ] **Step 2: Run tests and confirm RED**

Run: `tts_service/.venv/bin/python -m unittest tts_service.tests.test_cpu_client -v`

Expected: `TtsRealtimeClient` is missing because the current client is HTTP-only.

- [ ] **Step 3: Implement the reusable client and demo**

```python
with TtsRealtimeClient(url, api_key=key, ca_file=cert) as client:
    with output.open("wb") as pcm:
        for chunk in client.synthesize(["欢迎使用，", "这是双流语音服务。"]):
            pcm.write(chunk)
```

Use `websockets==15.0.1`, convert `https://host:8443/tts` to `wss://host:8443/tts/v1/realtime`, disable environment proxies, and never put the API key in URL/query parameters.

- [ ] **Step 4: Run client tests and all TTS CPU tests**

Run: `tts_service/.venv/bin/python -m unittest discover -s tts_service/tests -p 'test_*.py' -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tts_service/cpu_client tts_service/tests/test_cpu_client.py
git commit -m "feat: add reusable TTS WebSocket client"
```

### Task 6: Public contract, service docs, and monitoring wording

**Files:**
- Create: `contracts/tts-websocket.md`
- Modify: `contracts/openapi.yaml`
- Modify: `contracts/README.md`
- Modify: `contracts/validation.md`
- Modify: `tts_service/README.md`
- Modify: `tts_service/docs/validation.md`
- Modify: `gateway/README.md`
- Modify: `gateway/docs/validation.md`
- Modify: `README.md`
- Modify: `monitor_service/README.md`
- Create: `tts_service/tests/test_contract.py`

**Interfaces:**
- OpenAPI advertises only the TTS WebSocket GET/101 handshake and points `x-websocket-contract` to `tts-websocket.md`.
- Documentation uses `fun-cosyvoice3-0.5b-2512`, `aishell3-female`, 24 kHz PCM, and utterance-level TTFT consistently.

- [ ] **Step 1: Write failing static contract tests**

```python
def test_openapi_exposes_only_tts_websocket(self):
    text = (ROOT / "contracts/openapi.yaml").read_text()
    self.assertIn("/tts/v1/realtime:", text)
    self.assertNotIn("/tts/v1/audio/speech:", text)
    self.assertNotIn("/tts/v1/audio/voices:", text)
    self.assertIn("x-websocket-contract: ./tts-websocket.md", text)
```

Also assert no supported-interface table or README describes TTS as HTTP, 22050 Hz, seven preset voices, or `cosyvoice-300m-instruct`.

- [ ] **Step 2: Run tests and confirm RED**

Run: `tts_service/.venv/bin/python -m unittest tts_service.tests.test_contract -v`

Expected: old HTTP paths and model descriptions are still present.

- [ ] **Step 3: Replace the contract and documentation**

Document every message/event, binary PCM ordering, state transition, size/timeout/concurrency limit, handshake failures, fatal/recoverable errors, public/internal key separation, and utterance TTFT semantics from the approved spec. Remove old HTTP schemas and public health route from OpenAPI.

- [ ] **Step 4: Run contract tests and diff validation**

Run:

```bash
tts_service/.venv/bin/python -m unittest tts_service.tests.test_contract -v
git diff --check
```

Expected: tests pass and no whitespace errors are reported.

- [ ] **Step 5: Commit**

```bash
git add README.md contracts tts_service/README.md tts_service/docs/validation.md \
  gateway/README.md gateway/docs/validation.md monitor_service/README.md \
  tts_service/tests/test_contract.py
git commit -m "docs: publish CosyVoice3 WebSocket contract"
```

### Task 7: Provision and prove CoreX model compatibility

**Files:**
- Modify if evidence requires it: `tts_service/patches/corex-onnx-provider.patch`
- Modify if evidence requires it: `tts_service/scripts/bootstrap.sh`
- Create: `tts_service/scripts/validate_bistream.py`
- Modify: `tts_service/docs/validation.md`

**Interfaces:**
- Produces a validated `.venv`, pinned CosyVoice source, complete shared model snapshot, derived AISHELL-3 reference voice, and a passing `service.py check`.
- `validate_bistream.py --config tts_service/config/server.json --output <pcm-path>` performs one complete request followed by a delayed three-chunk generator request and prints JSON timing/memory evidence.

- [ ] **Step 1: Provision pinned artifacts**

Run: `bash tts_service/scripts/bootstrap.sh`

Expected: downloads finish with checksum verification and no replacement of CoreX torch/torchaudio.

- [ ] **Step 2: Verify complete-text inference on GPU 0**

Run:

```bash
tts_service/.venv/bin/python tts_service/scripts/validate_bistream.py \
  --config tts_service/config/server.json \
  --output tts_service/runtime/cosyvoice3-bistream-smoke.pcm
```

The helper first runs a complete request using the fixed prompt and one short Chinese sentence. Capture exit status, first PCM time, total PCM bytes, RTF, stable memory, and peak memory.

Expected: non-empty 24 kHz PCM and finite timings without unsupported operators.

- [ ] **Step 3: Verify strict model-level bi-streaming**

Feed at least three coherent Chinese chunks 50–100 ms apart into `TextStream`, delay `finish()`, and record monotonic timestamps for input chunks, first speech token, first PCM, and finish. Assert first PCM precedes `finish()`.

- [ ] **Step 4: Apply only evidence-driven CoreX fixes**

If the checks fail, preserve the full local traceback, identify the first unsupported dependency/operator, add the smallest pinned patch or compatible frontend version, and repeat Steps 1–3. Do not enable vLLM/TRT/JIT or alter the WebSocket contract to hide a failed bi-streaming path.

- [ ] **Step 5: Record validation evidence and commit**

Write exact commands, versions, model/source/voice hashes, measured timings, GPU memory, PCM metadata, and pass/fail results to `tts_service/docs/validation.md`.

```bash
git add tts_service/patches tts_service/scripts/bootstrap.sh tts_service/docs/validation.md
git commit -m "test: validate CosyVoice3 on CoreX"
```

### Task 8: Cut over the live service and verify end to end

**Files:**
- Modify with measured results: `contracts/validation.md`
- Modify with measured results: `gateway/docs/validation.md`
- Modify with measured results: `tts_service/docs/validation.md`

**Interfaces:**
- Produces a running TTS service on loopback port 8004 and public `WSS /tts/v1/realtime` on shared TLS port 8443.

- [ ] **Step 1: Run the complete pre-cutover test suite**

Run:

```bash
tts_service/.venv/bin/python -m unittest discover -s tts_service/tests -p 'test_*.py' -v
source yolov5v70-service/scripts/corex_env.sh
python -m unittest discover -s gateway/tests -p test_gateway.py -v
python -m unittest discover -s monitor_service/tests -p 'test_*.py' -v
python3 gateway/service.py check
git diff --check
```

Expected: all tests pass, NGINX config test passes, and diff check is clean.

- [ ] **Step 2: Stop v1 and start CosyVoice3**

Run:

```bash
python3 gateway/service.py stop --service tts
python3 gateway/service.py start --service tts
python3 gateway/service.py status --service tts
```

Expected: TTS reports `managed: true` and `ready: true`. If it does not, restore the previous TTS process before ending the deployment attempt.

- [ ] **Step 3: Reload the gateway only after internal readiness**

Run:

```bash
python3 gateway/service.py reload --service gateway
python3 gateway/service.py status --service gateway
```

Expected: gateway remains ready and NGINX now exposes only the TTS WebSocket route.

- [ ] **Step 4: Exercise public WebSocket reuse and monitoring**

Use the CPU client through `wss://localhost:8443/tts` with the shared gateway key and CA certificate. Send three utterances over one socket, save PCM, verify each `audio.done`, and confirm old HTTP paths return 404. Call `/monitor/v1/overview?refresh=true` and verify TTS is `running`, memory is non-null, and TTFT has a recent sample.

- [ ] **Step 5: Record evidence and run final verification**

Update the three validation documents with timestamps, commands, request/event sequence, PCM hashes/durations, memory, TTFT, and route-removal results. Then rerun the complete commands from Step 1 plus the public smoke client.

- [ ] **Step 6: Commit**

```bash
git add contracts/validation.md gateway/docs/validation.md tts_service/docs/validation.md
git commit -m "test: record CosyVoice3 deployment validation"
```
