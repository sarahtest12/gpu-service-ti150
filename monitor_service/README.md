# GPU 算法监控服务

本服务只监听 `127.0.0.1:8005`，由统一 NGINX 入口公开
`GET /monitor/v1/overview`。它每 5 秒采集一次，返回已部署算法的运行状态、显存和最近 60 秒耗时；
未部署服务不返回，异常服务只返回名称与状态。

耗时来自算法进程自身的 Prometheus 直方图。YOLO 使用每帧模型推理时间，VLM 使用首 token，
RAG 使用 vLLM 端到端请求时间，ASR 使用每轮 vLLM 解码首文本 token，TTS 使用每个 HTTP 请求
首次语音 token。显存通过 `ixsmi` 获取，并沿 `/proc` 父进程关系归属到网关管理的服务进程组。
`ixsmi` 的 MiB 会换算为十进制 MB。

```bash
python3 monitor_service/scripts/service.py check
python3 gateway/service.py start --service monitor
python3 gateway/service.py status --service monitor
python3 gateway/service.py stop --service monitor
```

内部 `/health` 和 `/v1/overview` 都需要 `monitor_service/runtime/api_key`，不应直接暴露。
统一入口使用公开 `GPU_API_KEY`，并替换为此内部凭据。
