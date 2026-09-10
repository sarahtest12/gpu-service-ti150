# BI-V150 算法服务

CPU 服务器部署 Web 应用与业务逻辑，GPU 主机通过统一 HTTPS 入口提供算法能力。
所有已接入算法共用一个对外端口和 `GPU_API_KEY`，按路径分发；不设置调用方 IP 或域名白名单。

| 能力 | GPU 主机对外接口 | 内部地址 |
| --- | --- | --- |
| VLM 图文、工具与 SSE | `https://GPU_HOST:8443/vlm/v1/chat/completions` | `127.0.0.1:8000` |
| VLM 模型列表 | `https://GPU_HOST:8443/vlm/v1/models` | 同上 |
| YOLO 视频帧双向流 | gRPC `GPU_HOST:8443`，方法路径 `/detector.v1.Detector/Detect` | `127.0.0.1:50051` |
| 服务状态 | `/health/live`、`/vlm/health/ready`、`/yolo/health/ready` | 由网关分别检查 |

状态接口也需要统一 key。YOLO 保留原有 gRPC 契约；普通 HTTP 单图接口、RAG、ASR 和 TTS 尚未实现。
规划的后续路径为 `/rag/v1/embeddings`、`/rag/v1/rerank`、`/asr/v1/audio/transcriptions`、
`/tts/v1/audio/speech`；未实现的路径当前返回 404。

## 部署与管理

1. 按 [网关说明](gateway/README.md) 构建 NGINX、配置证书和初始化凭据。
2. 按 [YOLO 说明](yolov5v70-service/README.md) 和 [VLM 说明](vlm_service/README.md) 准备各自环境与模型。
3. 从仓库根目录统一管理三个独立进程：

```bash
python3 gateway/service.py start
python3 gateway/service.py status
python3 gateway/service.py stop
```

`start` 返回表示进程正在启动，`status` 中各项 `ready: true` 才表示对应接口就绪。
也可加 `--service gateway`、`--service yolo` 或 `--service vlm` 独立操作；一个模型未就绪不会阻止网关转发另一个。
后台开发模式没有自动恢复；生产 systemd 的独立进程管理模板见网关说明。

网关配置位于 `gateway/config/server.json`。两个算法各用独立 Python 环境，网关不加载模型或 GPU 包。
本机固定 YOLO 使用 GPU 0，VLM 使用 GPU 1，模型共存能力以实测结果为准。
`bi150/` 为厂商参考资料；实际运行包以项目环境检查结果为准。

## CPU 后端调用

CPU 端复制需要的算法 `cpu_client/`；YOLO 还需复制同级 `shared/`。安装各客户端的 CPU 依赖，
使用 `config.gateway.example.json`，把 `GPU_HOST` 改成 GPU 的实际访问地址。
两边都通过 `GPU_API_KEY` 环境变量读取同一把对外 key；开发证书放在各配置文件旁，或通过
`GPU_CA_FILE` 指向同一个绝对路径。只传递证书文件，不传递证书私钥或算法内部 key。

VLM 使用 `VlmClient.stream_chat()` 或 `demo.py --stream` 逐段读取输出；
CPU Web 后端和浏览器也需逐段转发/读取，算法 key 仅保存在 CPU 后端。
前后端应用与业务数据权限管理由 CPU 项目实现。
