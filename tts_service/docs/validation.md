# CosyVoice-300M-Instruct 部署验收

日期：2026-09-11。GPU 主机为双 BI-V150 32 GiB；TTS 与 YOLO、BGE-M3、ASR 共用 GPU 0，
VLM 使用 GPU 1。模型来自本机 BI150 资料中的已验证目录，运行时使用 CoreX
`torch/torchaudio 2.7.1+corex.4.4.0` 和厂商 CosyVoice v1 实现。

## 已完成检查

| 验证 | 结果 |
| --- | --- |
| 固定模型目录、模型元数据与关键厂商源码 SHA-256 | 通过 |
| CoreX torch、CosyVoice 依赖与离线导入 | 通过 |
| TTS 服务鉴权、字段限制、PCM 转换、取消清理、并发、日志脱敏及首 token | 7 项通过 |
| 真实 NGINX/TLS/HTTP/SSE/WebSocket/gRPC/监控测试桩 | 15 项通过 |
| 统一公开 key 替换为 TTS 内部 key | 通过 |
| TTS PCM 首段在上游生成完成前经 NGINX 到达 | 通过 |
| TTS 并发额度与 VLM 等其他算法隔离 | 通过 |
| `/tts/docs`、`/tts/metrics`、`/tts/v1/models` 不公开 | 均为 404 |
| 7 个预置音色和 TTS 就绪接口经统一入口访问 | 通过 |
| 厂商日志中的请求文本与指令过滤 | 通过；日志保留请求 ID、首段耗时和音频段耗时 |

真实模型内部接口合成“欢迎使用语音服务。”，返回 193536 字节 PCM，封装为 22050 Hz、单声道、
16-bit WAV 后共 96768 帧、4.389 秒。该次首段音频约 29.672 秒到达，总耗时约 38.828 秒。
模型成功流式分三段产生音频，但当前性能不适合作为低延迟实时语音承诺。后续应使用业务文本、
不同音色和预热后的多轮样本测量 P50/P95。

服务按最终代码重启后，经 `https://localhost:8443/tts/v1/audio/speech` 和统一公开 key 合成
“统一网关语音测试。”，首段约 8.969 秒、总耗时约 8.974 秒；返回 101376 字节 PCM，封装后
为 50688 帧、2.299 秒音频。该短文本只产生一个模型音频块，因此不能用它单独证明真实模型会在
所有文本上较早出首包；NGINX 测试桩另行验证了多块 PCM 不被缓冲。

为确认日志脱敏，另经统一入口合成带唯一标记的短文本，得到 192512 字节 PCM；首段约
19.386 秒、总耗时约 20.900 秒。服务日志中未出现输入文本或指令，仅记录请求 ID、首段耗时、
音频段长度和 RTF。

服务加载并完成一次合成后，`ixsmi` 显示 TTS 进程约 2150 MiB。GPU 0 总占用约 14054 MiB，
GPU 1 总占用约 27052 MiB；这是当时的进程显存快照，不是并发峰值或硬限制。

启动日志中的 `CUDAExecutionProvider` 缺失警告来自用于语音提示特征的 ONNX Runtime 会话；当前
固定预置音色 Instruct 接口不接收提示音频，实际合成主模型在 GPU 执行。还存在厂商依赖的弃用
警告和 `ttsfrd` 缺失后切换到 WeTextProcessing 的提示，本次没有造成接口或推理失败。

2026-09-11 增加监控后执行两次真实短文本合成，首语音 token 分别约 2.053 秒与 7.478 秒；
后一次所在 60 秒快照的 avg/P95 为 7478.046/9984.0 ms。P95 是直方图桶内估算，因此单样本时
不等于该样本原值。`/tts/metrics` 仍不公开，只允许本机监控服务使用 TTS 内部 key 读取。

## 复现

```bash
bash tts_service/scripts/bootstrap.sh
python3 gateway/service.py start --service tts
python3 gateway/service.py reload --service gateway
python3 gateway/service.py status --service all
tts_service/.venv/bin/python -m unittest discover -s tts_service/tests -p 'test_*.py' -v
source yolov5v70-service/scripts/corex_env.sh
python -m unittest discover -s gateway/tests -p test_gateway.py -v
```

CPU 服务器跨机网络、正式证书、长时间稳定性、目标业务音质和并发容量尚未在本机验收。
