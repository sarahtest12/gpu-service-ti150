# CosyVoice-300M-Instruct 流式 TTS

本服务在 BI-V150 GPU 0 上运行本机已验证的 `CosyVoice-300M-Instruct`。推理由厂商
CosyVoice v1 PyTorch/TorchScript 代码执行，FastAPI/Uvicorn 提供内部 HTTP 服务，NGINX
统一暴露 `https://GPU_HOST:8443/tts/...`。它不使用 vLLM，也不开放模型原生管理接口。

## 配置与运行边界

[`config/server.json`](config/server.json) 是运行配置的唯一来源：

| 配置 | 当前值 |
| --- | --- |
| 模型目录 | `/share/fshare/common/models/CosyVoice/CosyVoice-300M-Instruct` |
| 厂商源码 | `/root/llm-infer/transformers/audio/CosyVoice-300M-Instruct/CosyVoice` |
| 对外模型名 | `cosyvoice-300m-instruct` |
| 设备 / 精度 | GPU 0 / FP16，TorchScript LLM 与 encoder |
| 内部监听 | `127.0.0.1:8004` |
| 输出 | 22050 Hz、单声道、little-endian signed PCM16 |
| 文本 / 指令上限 | 2000 / 500 个 Unicode 字符 |
| 并发 | 1 个活跃合成请求 |

服务锁定当前 CoreX torch/torchaudio、模型元数据及关键厂商源码的 SHA-256。独立 `.venv`
通过 `--system-site-packages` 复用 CoreX，不安装通用 PyTorch、CUDA、vLLM 或
`onnxruntime-gpu`。`speech_tokenizer_v1.onnx` 初始化时使用 CPU ONNX Runtime；固定预置音色的
Instruct 合成主路径在 GPU 执行。

当前提供检查点中的 7 个预置音色：`中文女`、`中文男`、`粤语女`、`日语男`、`英文女`、
`英文男`、`韩语女`。不提供参考音频克隆、音色上传、MP3/WAV 编码或流式变速。

## 准备与管理

从仓库根目录执行：

```bash
bash tts_service/scripts/bootstrap.sh
python3 gateway/service.py start --service tts
python3 gateway/service.py status --service tts
python3 gateway/service.py reload --service gateway
```

`ready: true` 表示模型和必要组件已加载并开始监听。内部 key 位于忽略提交的
`tts_service/runtime/api_key`，仅供网关注入；CPU 后端仍使用统一的
`gateway/runtime/api_key`。不要向 CPU 项目复制 TTS 内部 key。

停止和重新加载模型：

```bash
python3 gateway/service.py stop --service tts
python3 gateway/service.py start --service tts
```

开发后台模式没有自动恢复。生产主机可使用现有 `gpu-algorithm@tts.service` systemd 模板，
按安装目录和运行用户调整。运行日志、PID 和创建时间由网关管理器保存在 `gateway/runtime/`。

## 对外接口

所有路径要求 `Authorization: Bearer <GPU_API_KEY>`。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/tts/v1/audio/speech` | 流式生成原始 PCM |
| GET | `/tts/v1/audio/voices` | 列出允许使用的预置音色 |
| GET | `/tts/health/ready` | TTS 就绪状态 |

内部 `/metrics` 发布 `tts_time_to_first_token_seconds` 直方图。每个 HTTP 合成请求只记录首次
语音 token，从语音 token 解码器开始工作到第一次产出；它不等于首段 PCM 到达时间。
该路径要求 TTS 内部 key，统一网关不直接公开，仅由本机监控服务采集。

合成请求：

```json
{
  "model": "cosyvoice-300m-instruct",
  "input": "欢迎使用语音服务。",
  "voice": "中文女",
  "instructions": "用自然、亲切的语气播报。",
  "response_format": "pcm",
  "stream": true,
  "speed": 1.0
}
```

`model`、`input`、`voice` 必填。`instructions` 省略、`null` 或空白时使用中性播报指令；
输入与指令不得含模型分词器控制序列。其余三个字段可省略，但当前只接受示例中的固定值。

成功响应为 `audio/pcm` 的连续字节流，并通过 `X-Audio-Format: pcm_s16le`、
`X-Audio-Sample-Rate: 22050`、`X-Audio-Channels: 1` 描述格式。响应没有 `Content-Length`；
HTTP chunk 边界只是传输边界，不能当作音频帧边界。NGINX 已关闭该路径的响应缓冲和缓存。

模型或音色错误返回 400/404，结构校验返回 422，请求体超过 16 KiB 返回 413，并发占满返回
429，上游不可用通常返回 502。音频头已经发送后发生的推理错误会表现为 PCM 流提前结束，
CPU 业务不能仅凭 HTTP 200 判断音频完整。CosyVoice v1 没有单次生成的计算取消接口；客户端
断开后服务会把生成器执行完并清理缓存，在此之前新的请求仍会得到 429。

完整字段和响应见 [`../contracts/openapi.yaml`](../contracts/openapi.yaml)。本服务的流式输出表示
首段可在整段完成前发送，并不承诺低延迟实时播放；当前机器的三个短文本样本首段约为
9.0–29.7 秒。

## CPU 客户端与验证

[`cpu_client/`](cpu_client/README.md) 可独立复制到 CPU Web 后端，只依赖 HTTPX。示例把分块 PCM
安全地封装成 WAV；在线业务也可以按返回头把 PCM 逐块转发给播放器。

```bash
tts_service/.venv/bin/python -m unittest discover -s tts_service/tests -p 'test_*.py' -v
source yolov5v70-service/scripts/corex_env.sh
python -m unittest discover -s gateway/tests -p test_gateway.py -v
```

真实模型和统一入口验收记录见 [`docs/validation.md`](docs/validation.md)。
