# CPU 后端实时 ASR 客户端

将本目录复制到 CPU Web 后端。安装 `requirements.txt`，复制 GPU 网关证书，基于
`config.gateway.example.json` 创建 `config.gateway.json`，并通过 `GPU_API_KEY` 提供统一的对外 key。

业务代码使用 `RealtimeAsrClient.connect()` 建立长连接，调用 `session.start()` 后发送
16 kHz、单声道、little-endian signed PCM16 字节帧，同时循环调用 `session.receive()` 读取 partial；
结束时调用 `session.stop()`，读到 `{"event":"stopped"}` 后关闭连接。推荐每帧 100 ms，即 3200 字节。

`demo.py` 只是把 PCM WAV 按实时节奏回放到 WebSocket，用于联调；GPU 服务没有完整文件转写接口。
浏览器不应持有 `GPU_API_KEY`，由 CPU Web 后端连接 GPU，再把业务需要的结果推送给浏览器。

