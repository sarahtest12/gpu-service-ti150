# CosyVoice-300M CPU 客户端

该目录可独立复制到 CPU Web 后端，不依赖 GPU、CoreX 或 torch。客户端通过统一网关
`WSS /tts/v1/realtime` 和公开 `GPU_API_KEY` 建立长连接，握手必须返回：

- 模型 `cosyvoice-300m-instruct`
- 固定音色 `中文女`
- 22050 Hz、单声道、PCM S16LE

安装依赖，复制并修改示例配置中的 GPU 地址和可信证书：

```bash
python -m pip install -r requirements.txt
GPU_API_KEY='统一公开key' python demo.py \
  --config config.gateway.example.json \
  --output output.wav < sentences.txt
```

`sentences.txt` 每行是一段由 CPU 业务已经断好的文本。Demo 用独立生产线程发送，用当前线程持续
接收 PCM；只等待接管确认，不等待前段音频完成。WAV 采样率从 `session.created.audio` 读取。

核心 API：

- `send_segment(segment_id, text)`：提交完整段，是否被 GPU 接管由接收事件确认。
- `receive_segment_frame()`：返回 `SegmentFrame(kind, segment_id, pcm)`；只允许一个接收者。
- `cancel_segment(segment_id)`：取消当前活动段并清空 GPU 等待队列。

`kind` 只可能为 `accepted`、`audio_start`、`audio`、`audio_done` 或 `cancelled`。发送与接收可在
不同线程并行；PCM 根据最近的 `audio_start` 关联到段，服务保证不同段不交错。

每段最多 2000 个 Unicode 字符。等待队列最多 8 段、4096 字符，不含活动段。`queue_full` 通过
`SegmentRejected` 报告，连接仍可用，容量释放后可用同一 ID 重试；已经收到 `accepted` 的 ID 在
整个连接中不能复用。

取消后继续读取到 `cancelled`。底层生成器不可抢占，确认可能延迟；确认到达前暂停新提交并立即
清空浏览器播放器。致命错误或断线抛出 `SegmentStreamError`，其 `unfinished_segment_ids` 是保守
快照；不要自动重放可能已经播放过一部分的内容。

下面是三段流水线的基本结构：

```python
import os
import threading
from tts_client import SegmentRejected, SegmentStreamError, TtsRealtimeClient

with TtsRealtimeClient(
    "https://GPU_HOST:8443/tts",
    api_key=os.environ["GPU_API_KEY"],
    ca_file="/path/to/server.crt",
) as client:
    assert client.session["model"] == "cosyvoice-300m-instruct"
    configure_browser_audio(**client.session["audio"])

    def produce():
        client.send_segment("reply-1-seg-1", "第一句。")
        client.send_segment("reply-1-seg-2", "第二句。")
        client.send_segment("reply-1-seg-3", "第三句。")

    producer = threading.Thread(target=produce)
    producer.start()
    completed = set()
    try:
        while len(completed) < 3:
            try:
                frame = client.receive_segment_frame()
            except SegmentRejected as error:
                schedule_retry(error.segment_id, error.code)
                continue
            if frame.kind == "audio":
                send_pcm_to_browser(frame.pcm)
            elif frame.kind == "audio_done":
                completed.add(frame.segment_id)
    except SegmentStreamError as error:
        fail_reply(error.unfinished_segment_ids)
    finally:
        producer.join()
```

key 只保存在 CPU 后端，不放入浏览器、URL 或日志。浏览器只接收业务后端转发的音频与状态。
