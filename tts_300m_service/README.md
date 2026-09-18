# CosyVoice-300M TTS 服务

该目录独立部署 `CosyVoice-300M-Instruct`，是统一网关当前默认的 TTS 上游。原
[`tts_service`](../tts_service/README.md) 已恢复为 Fun-CosyVoice3 双流服务，两套代码和运行时
凭据互不混用；它们都监听 `127.0.0.1:8004`，因此只能启动其中一个。

公开入口保持不变：

- `WSS https://GPU_HOST:8443/tts/v1/realtime`
- 请求头：`Authorization: Bearer <GPU_API_KEY>`
- 固定模型：`cosyvoice-300m-instruct`
- 固定音色：`中文女`
- 固定模式：Instruct；服务端使用英文 instruction 和固定随机种子，客户端不能修改
- 数字读法：阿拉伯数字统一经过中文文本规范化；日期、金额、小数、百分比等按中文上下文展开
- 输出：22050 Hz、单声道、little-endian PCM S16LE

CPU 端先断句，然后可在前一段仍在合成时继续发送完整分段。服务按 FIFO 返回音频，不会交错
不同段的 PCM。完整帧协议见 [`../contracts/tts-websocket.md`](../contracts/tts-websocket.md)。

## 环境与制品

配置在 [`config/server.json`](config/server.json)，固定使用 BI150 已提供的：

- 模型：`/share/fshare/common/models/CosyVoice/CosyVoice-300M-Instruct`
- 源码：`/root/llm-infer/transformers/audio/CosyVoice-300M-Instruct/CosyVoice`
- CoreX PyTorch 2.7.1、FP16、JIT；关闭 ONNX

配置校验源码和关键模型文件哈希，并检查 JIT 制品存在。不会下载或替换厂商制品。执行 bootstrap
会根据 hash lock 创建本目录自己的 `.venv`；若已有环境，会先保留为 `.venv.stale-*`，失败时自动
恢复。

```bash
bash tts_300m_service/scripts/bootstrap.sh
tts_300m_service/.venv/bin/python tts_300m_service/scripts/service.py check
tts_300m_service/.venv/bin/python tts_300m_service/scripts/service.py init-key
```

网关管理器默认把 `tts` 映射到该目录：

```bash
python3 gateway/service.py stop --service tts
python3 gateway/service.py start --service tts
python3 gateway/service.py status --service tts
```

`ready: true` 才表示模型已加载。内部 `/health`、`/metrics` 和 `/realtime` 只监听 loopback，并使用
`tts_300m_service/runtime/api_key`；CPU 服务器只使用统一公开 `GPU_API_KEY`。
如果该内部 key 相比当前运行配置发生变化，还要重启监控并重载网关，使两个进程重新读取 key：

```bash
python3 gateway/service.py stop --service monitor
python3 gateway/service.py start --service monitor
python3 gateway/service.py reload --service gateway
```

## 分段协议

握手首帧固定为：

```json
{
  "type": "session.created",
  "session_id": "tts_...",
  "model": "cosyvoice-300m-instruct",
  "voice": "中文女",
  "audio": {"format": "pcm_s16le", "sample_rate_hz": 22050, "channels": 1}
}
```

提交一段：

```json
{"type":"input.segment","segment_id":"reply-1-seg-1","text":"第一句话。"}
```

服务依次返回 `input.accepted`、`audio.start`、一个或多个二进制 PCM 帧、`audio.done`。单段最多
2000 个 Unicode 字符；等待队列最多 8 段和 4096 字符，活动段不计入。超过模型内部长度的文本
先使用原生 `text_normalize(split=True)`，仍过长时按约 80 个单元继续切分。

活动段可用 `response.cancel` 取消。服务会清空等待队列、排空当前不可抢占的厂商生成器，再返回
`response.cancelled`；收到确认前不能提交新段。确认后 WebSocket 可复用。实测取消清理可能需要
十余秒，CPU 端和播放器应立即停止追加/播放，并继续读取到确认事件。

## CPU 客户端

复制 [`cpu_client`](cpu_client/) 到 CPU Web 后端，安装其中依赖，按行提供已经断好的句子：

```bash
GPU_API_KEY='统一公开key' python cpu_client/demo.py \
  --config cpu_client/config.gateway.example.json \
  --output output.wav < sentences.txt
```

业务代码使用 `send_segment()` 与 `receive_segment_frame()` 并行生产和消费；音频参数必须读取
`client.session["audio"]`。断线时不要自动重放可能已播放过的段。

## 验证

```bash
PYTHONPATH="$PWD/tts_300m_service/.venv/lib/python3.10/site-packages:/usr/local/corex/lib64/python3/dist-packages" \
  tts_300m_service/.venv/bin/python -m unittest discover \
  -s tts_300m_service/tests -p 'test_*.py' -v
```

停止常驻 TTS 后可运行直接 GPU 基准：

```bash
tts_300m_service/.venv/bin/python tts_300m_service/scripts/validate_segments.py \
  --output tts_300m_service/runtime/validation-segments.pcm
```

真实测试记录见 [`docs/validation.md`](docs/validation.md)。
