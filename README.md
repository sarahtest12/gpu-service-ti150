# BI-V150 算法服务

CPU 服务器部署 Web 应用与业务逻辑，GPU 主机通过统一 HTTPS 入口提供算法能力。
所有已接入算法共用一个对外端口和 `GPU_API_KEY`，按路径分发；不设置调用方 IP 或域名白名单。

接口 review 入口见 [契约总览](contracts/README.md)：包含 OpenAPI 3.1.1、YOLO gRPC 契约说明，
并区分已实现接口和尚未实现的预留路径。

| 能力 | GPU 主机对外接口 | 内部地址 |
| --- | --- | --- |
| VLM 图文、工具与 SSE | `https://GPU_HOST:8443/vlm/v1/chat/completions` | `127.0.0.1:8000` |
| VLM 模型列表 | `https://GPU_HOST:8443/vlm/v1/models` | 同上 |
| YOLO 视频帧双向流 | gRPC `GPU_HOST:8443`，方法路径 `/detector.v1.Detector/Detect` | `127.0.0.1:50051` |
| RAG 文本向量 | `/rag/v1/embeddings`，模型 `bge-m3` | `127.0.0.1:8002` |
| RAG 模型列表 | `/rag/v1/models` | 同上 |
| ASR 实时语音识别 | `wss://GPU_HOST:8443/asr/v1/realtime`，模型 `Fun-ASR-Nano-2512` | `127.0.0.1:8003` |
| TTS 流式语音合成 | `wss://GPU_HOST:8443/tts/v1/realtime`，默认 `CosyVoice-300M-SFT` 分段 FIFO | `127.0.0.1:8004` |
| 性能监控快照 | `/monitor/v1/overview` | `127.0.0.1:8005` |
| 服务状态 | `/health/live`、VLM/YOLO/RAG/ASR 就绪路径及 `/monitor/v1/overview` | TTS 由监控读取内部健康状态 |

状态接口也需要统一 key。RAG 当前提供 BGE-M3 的 1024 维文本向量，不部署 reranker；
文档分块、向量库、召回和权限由 CPU 项目实现。YOLO 保留原有 gRPC 契约；ASR 只提供实时
WebSocket，不提供完整文件转写接口。默认 TTS 接收 CPU 断好的分段并按 FIFO 合成，返回
22050 Hz 单声道 PCM S16LE；原 `tts_service` 的 CosyVoice3 双流实现保留，但网关默认启动独立的
`tts_300m_sft_service`。普通 HTTP 单图接口和
`/rag/v1/rerank` 尚未实现，当前返回 404。

## 部署与管理

1. 按 [网关说明](gateway/README.md) 构建 NGINX、配置证书和初始化凭据。
2. 按 [YOLO 说明](yolov5v70-service/README.md)、[VLM 说明](vlm_service/README.md)、[RAG 说明](rag_service/README.md)、[ASR 说明](asr_service/README.md)、[默认 TTS 说明](tts_300m_sft_service/README.md) 和 [监控说明](monitor_service/README.md) 准备各自服务。
3. 从仓库根目录统一管理网关、五个算法服务和监控，共七个独立进程组：

```bash
python3 gateway/service.py start
python3 gateway/service.py status
python3 gateway/service.py stop
```

`start` 返回表示进程正在启动，`status` 中各项 `ready: true` 才表示对应接口就绪。
也可加 `--service gateway`、`--service yolo`、`--service vlm`、`--service rag`、`--service asr`、`--service tts` 或 `--service monitor` 独立操作；一个模型未就绪不会阻止网关转发另一个。
新增路由可用 `python3 gateway/service.py reload --service gateway` 检查配置并重载已运行的网关。
后台开发模式没有自动恢复；生产 systemd 的独立进程管理模板见网关说明。

网关配置位于 `gateway/config/server.json`。各算法使用独立 Python 环境，网关不加载模型或 GPU 包。
本机 YOLO、BGE-M3 与 Fun-ASR-Nano 使用 GPU 0，VLM 使用 GPU 1，模型共存能力以实测结果为准。
`bi150/` 为厂商参考资料；实际运行包以项目环境检查结果为准。

## CPU 后端调用

CPU 端复制需要的算法 `cpu_client/`；YOLO 还需复制同级 `shared/`。安装各客户端的 CPU 依赖，
使用 `config.gateway.example.json`，把 `GPU_HOST` 改成 GPU 的实际访问地址。
各客户端都通过 `GPU_API_KEY` 环境变量读取同一把对外 key；开发证书放在各配置文件旁，或通过
`GPU_CA_FILE` 指向同一个绝对路径。只传递证书文件，不传递证书私钥或算法内部 key。

VLM 使用 `VlmClient.stream_chat()` 或 `demo.py --stream` 逐段读取输出；
ASR 使用 `RealtimeAsrClient` 发送麦克风 PCM 帧并同时读取可修订 partial 与 final；
TTS 使用 `TtsRealtimeClient` 复用一条 WSS 会话，并行提交 CPU 已断好的完整分段并消费有序 PCM；
监控使用 `MonitorClient.overview()` 读取定时快照，页面手动刷新时传 `refresh=True`；
CPU Web 后端和浏览器也需逐段转发/读取，算法 key 仅保存在 CPU 后端。
前后端应用与业务数据权限管理由 CPU 项目实现。
