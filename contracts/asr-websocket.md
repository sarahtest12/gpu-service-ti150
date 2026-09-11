# ASR 实时 WebSocket 契约

连接地址为 `wss://GPU_HOST:8443/asr/v1/realtime`，握手头为
`Authorization: Bearer <GPU_API_KEY>`。TLS、端口和 key 与其他算法服务共用。服务只提供实时接口，
没有完整音频文件转写接口。

客户端发送文本 `START` 开始会话，服务返回 `{"event":"started"}`。随后客户端以二进制消息发送
16 kHz、单声道、little-endian signed PCM16；推荐每 100 ms 一帧（3200 字节）。服务会反复返回：

```json
{
  "sentences": [{"text": "已确认文本", "start": 420, "end": 2100}],
  "partial": "当前可能修订的文本",
  "partial_start_ms": 2100,
  "duration_ms": 3000,
  "is_final": false
}
```

`sentences` 是已经锁定的片段，时间单位为毫秒；`partial` 可在后续事件中修订或清空。
调用结束时客户端发送文本 `STOP`。服务先返回 `is_final=true` 的最终结果，再返回
`{"event":"stopped"}`。客户端必须读到 `stopped`，不能把任意一次 partial 当作完整结果。

开始后可以发送 `LANGUAGE:中文`、`LANGUAGE:English` 或 `LANGUAGE:日本語`，服务返回
`language_set` 确认；也可以发送 `HOTWORDS:词一,词二`，服务返回 `hotwords_set`。
当前使用服务端 VAD，不接受 `COMMIT`。未发送 `START` 时的二进制消息不会进入识别。

网关最多允许 4 个并发 ASR 长连接，单个 WebSocket 消息上限 1 MiB，空闲读取超时 3600 秒。
握手阶段可能返回 401（key 错误）、403（方法错误）、404（路径错误）、429（并发已满）、
502/504（ASR 上游不可用）。升级成功后的推理异常可能导致连接关闭，调用方不应自动重放已发送音频。
健康检查为 `GET /asr/health/ready`，同样使用公共 key，成功响应为
`200 application/json` 和 `{"status":"ok"}`。

OpenAPI 只能描述握手与健康检查，双向消息语义以本文件为准。

