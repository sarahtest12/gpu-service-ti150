# Fun-CosyVoice3-0.5B-2512 双向流式 TTS

本服务在 BI-V150 GPU 0 上运行 `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`。推理由官方 CosyVoice3
原生 PyTorch 路径执行，文本 generator 与 PCM 输出同时流动；不启用 vLLM、TensorRT 或 JIT。
FastAPI/Uvicorn 只监听 `127.0.0.1:8004`，NGINX 通过统一端口公开
`wss://GPU_HOST:8443/tts/v1/realtime`。

## 配置与运行边界

[`config/server.json`](config/server.json) 固定以下部署边界：

| 配置 | 当前值 |
| --- | --- |
| 模型 | `fun-cosyvoice3-0.5b-2512`，固定 Hugging Face revision |
| 推理 | GPU 0、FP16、原生 PyTorch `inference_bistream` |
| 内部监听 | `127.0.0.1:8004` |
| 输出 | 24000 Hz、单声道、little-endian PCM S16LE |
| 音色 | 固定 `aishell3-female` |
| 单文本块 / utterance | 最多 1024 / 4096 个 Unicode 字符 |
| 超时 | 活跃输入 300 秒；PCM 单帧发送 30 秒；空闲会话 3600 秒 |
| 并发 | 1 个活跃 WebSocket |
| 启动显存门禁 | GPU 0 至少保留 6000 MiB 可用显存 |

模型、官方源码、13 个运行所需模型文件的 SHA-256 和源码 revision 均由启动检查固定。
[`requirements.lock`](requirements.lock) 与 [`requirements-build.lock`](requirements-build.lock)
固定服务自带依赖的版本和安装包 SHA-256，bootstrap 以 `--require-hashes --no-deps` 安装，不在部署时
重新解析传递依赖，并在每次执行时从空虚拟环境重建。独立 `.venv` 优先加载这些包，再从 CoreX
基础镜像加载厂商 torch/torchaudio；[`config/corex-packages.json`](config/corex-packages.json) 固定
实际模型加载闭包中 92 个继承包的版本、安装根、RECORD 指纹和其中每个源码/二进制文件哈希。
模型加载后还会核对实际导入包集合，启动检查拒绝本地包残留或基础镜像依赖漂移。
不安装通用 PyTorch、CUDA、
`onnxruntime-gpu`、vLLM 或 TensorRT。语音 tokenizer 的 ONNX 会话明确使用 CPU provider，TTS
主模型在 GPU 执行。启动检查会实际分配一个 CUDA FP16 tensor，并验证官方源码仓库 HEAD、
完整允许差异和 Matcha-TTS 子模块 revision；模型加载后再次确认内部设备、FP16 标志和导入包集合。

固定参考音色来自 AISHELL-3 的 Apache-2.0 女声 SSB0005。来源 revision、原始文件哈希、裁剪点、
官方转写索引、文本和派生 24 kHz WAV 哈希记录在
[`assets/voices/aishell3-female.json`](assets/voices/aishell3-female.json)。客户端不能上传参考音频、
选择其他音色或调整速度。启动时还会检查 WAV 编码、时长、峰值、首尾静音和边缘噪声，避免被
替换为虽有匹配元数据但不适合作为参考音色的音频；bootstrap 会把文本与固定 revision 的
AISHELL-3 官方索引逐字核对，并要求内部估算信噪比不低于 25 dB。音色清单自身也由 SHA-256 固定。

## 准备与管理

从仓库根目录执行：

```bash
bash tts_service/scripts/bootstrap.sh
python3 gateway/service.py start --service tts
python3 gateway/service.py status --service tts
python3 gateway/service.py reload --service gateway
```

bootstrap 会重建虚拟环境、检出固定 revision 的官方 CosyVoice 源码、应用 CoreX CPU ONNX patch、
下载并校验模型、生成固定参考 WAV，再初始化内部 key。`ready: true` 表示模型和必要组件已加载并
开始监听。内部 key 位于 `tts_service/runtime/api_key`，只供网关和本机监控使用；CPU 后端使用
`gateway/runtime/api_key` 中的统一公开 key。

停止和重新加载模型：

```bash
python3 gateway/service.py stop --service tts
python3 gateway/service.py start --service tts
```

开发后台模式没有自动恢复。生产主机可使用现有 `gpu-algorithm@tts.service` systemd 模板，并按
实际安装目录和运行用户调整。

## 对外接口

唯一公开 TTS 业务接口是 `WSS /tts/v1/realtime`，握手要求
`Authorization: Bearer <GPU_API_KEY>`。连接成功后：

1. 服务端发送 `session.created`，声明模型、固定音色和 PCM 参数。
2. 客户端连续发送一个或多个 `input.text`。
3. 服务端发送 `audio.start`，并可在客户端发送 `input.done` 前持续发送二进制 PCM。
4. 客户端发送 `input.done`；服务端完成后发送 `audio.done`。
5. 收到 `audio.done` 后，同一 WebSocket 可开始下一条 utterance；空闲时发送 `session.close`。

完整帧格式、状态、限制与错误码见
[`../contracts/tts-websocket.md`](../contracts/tts-websocket.md)。旧的公开语音 HTTP、音色列表和 TTS
健康路径已移除；TTS 的 `/health` 与 `/metrics` 仍作为 loopback 内部接口保留，并要求内部 key。

内部 `/metrics` 发布 `tts_time_to_first_token_seconds`。每个 utterance 最多记录一次，从
`inference_bistream` 开始消费首批规范化文本 token，到首个语音 token 在 GPU 服务进程可见。
它不含等待客户端文本、PCM 解码和网络时间，也不等于客户端收到首段音频的延迟。

## CPU 客户端与验证

[`cpu_client/`](cpu_client/README.md) 可独立复制到 CPU Web 后端，只依赖 `websockets==15.0.1`。
客户端复用一条 WSS 会话，在后台消费 LLM 文本迭代器并同时向调用方产生 PCM。

```bash
TTS_VENV_SITE="$PWD/tts_service/.venv/lib/python3.10/site-packages"
PYTHONPATH="$TTS_VENV_SITE:/usr/local/corex/lib64/python3/dist-packages" \
  tts_service/.venv/bin/python -m unittest discover -s tts_service/tests -p 'test_*.py' -v
source yolov5v70-service/scripts/corex_env.sh
python -m unittest discover -s gateway/tests -p 'test_*.py' -v
```

真实 CoreX 模型、严格双流、统一入口和显存验收记录见
[`docs/validation.md`](docs/validation.md)。
