# Fun-ASR-Nano-2512 实时 ASR

本服务在 BI-V150 GPU 0 上运行 `FunAudioLLM/Fun-ASR-Nano-2512`。音频编码器和适配器使用
FunASR，文本解码使用机器中已有的 CoreX `vLLM 0.17.0`；服务端 VAD 在 CPU 上运行。
内部只监听 `127.0.0.1:8003`，CPU Web 后端通过共享网关访问
`wss://GPU_HOST:8443/asr/v1/realtime`。

部署锁定 FunASR 源码 revision `e42443f55971d0c804dcf2973fdd2e6e09bd5611` 和模型
`model.pt` SHA-256，避免上游实时协议或权重静默变化。模型目录为
`/share/fshare/common/models/FunAudioLLM/Fun-ASR-Nano-2512`。首次准备执行：

```bash
bash asr_service/scripts/bootstrap.sh
```

统一生命周期管理：

```bash
python3 gateway/service.py start --service asr
python3 gateway/service.py status --service asr
python3 gateway/service.py stop --service asr
python3 gateway/service.py reload --service gateway
```

`ready: true` 表示音频编码器、VAD 和 vLLM 解码器均已加载并开始监听。首次启动通常需要几十秒。
内部 key 位于忽略提交的 `asr_service/runtime/api_key`，只能由网关使用；CPU 后端继续使用
`gateway/runtime/api_key` 中的统一公共 key。

音频和返回事件见 [WebSocket 契约](../contracts/asr-websocket.md)。服务没有 HTTP 文件转写路径，
也未启用说话人分离。当前配置上限为 4 个并发连接，480 ms 调度一次首轮 partial，后续以
960 ms 音频增量触发模型解码，partial 滚动窗口为 8 秒。Fun-ASR-Nano 的实时实现会重复编码
滚动音频窗口，并非带因果缓存的流式声学编码器；并发与延迟上限需要按业务音频继续压测。

实际部署验证见 [验证记录](docs/validation.md)，CPU 调用示例见 [cpu_client](cpu_client/README.md)。

