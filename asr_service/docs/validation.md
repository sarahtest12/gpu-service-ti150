# Fun-ASR-Nano-2512 部署验证

验证日期：2026-09-10。GPU 主机为双 BI-V150 32 GiB，ASR 与 YOLO、BGE-M3 共用 GPU 0，
VLM 使用 GPU 1。

本机 CoreX `vLLM 0.17.0+corex.4.5.0.rc.11.20260701` 成功加载派生的 Qwen3-0.6B 解码器；
模型样例 `example/zh.mp3` 的直接推理输出为“开饭时间早上九点至下午五点。”。
该次探针音频编码约 685 ms，vLLM 生成约 480 ms，仅用于兼容性确认。

通过统一网关进行 5.616 秒音频的实时回放，使用 100 ms PCM16 帧。WebSocket 握手经过 TLS、
公共 API key、NGINX 路由和内部 ASR key。约 2.15 秒收到首个非空 partial，随后连续修订，
约 6.11 秒收到最终句子，文本同上，时间范围为 420–5610 ms。所有已部署服务状态同时为 ready。

该次调用后 `ixsmi` 报告 ASR 主进程约 1634 MiB、vLLM EngineCore 约 7732 MiB，合计约
9366 MiB。GPU 0 上连同 BGE-M3 与 YOLO 的总占用约 11892 MiB，仍有约 20 GiB 余量。
这是进程显存快照，包含 vLLM 预留，不等同于单次请求实际张量峰值。

这里的首 partial 时间包含客户端累计音频、服务端 VAD、滚动窗口推理和网络调度，不能直接视为
模型纯推理基准。单样例也不能代表生产 P95；正式并发容量仍需使用目标麦克风、噪声和口音数据压测。
