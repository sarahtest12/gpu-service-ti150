# CPU 后端调用双向流式 TTS

此目录可独立复制到 CPU Web 后端，不依赖 GPU、CoreX 或 torch。客户端通过统一网关的
`WSS /tts/v1/realtime` 建立长连接；一条连接可以顺序合成多段话。服务端固定使用
`aishell3-female` 音色，输出 24000 Hz、单声道 PCM S16LE。

安装依赖，复制 `config.gateway.example.json` 为 `config.gateway.json`，把 `GPU_HOST` 替换为
GPU 服务器地址，并放置覆盖该地址的可信证书：

```bash
python -m pip install -r requirements.txt
GPU_API_KEY='统一公开key' python demo.py \
  --config config.gateway.json \
  --text '欢迎使用语音服务。' \
  --output output.wav
```

通过安全配置向 CPU 后端注入与其他算法共用的 `GPU_API_KEY`。浏览器不应持有该 key；不要复制
GPU 上的 TTS 内部 key 或 TLS 私钥。`ca_file` 可省略，此时使用操作系统信任库。

Web 后端可保持客户端对象并按顺序复用连接：

```python
import os
import threading
from tts_client import TtsRealtimeClient, TtsTextInput

with TtsRealtimeClient(
    "https://GPU_HOST:8443/tts",
    api_key=os.environ["GPU_API_KEY"],
    ca_file="/path/to/server.crt",
) as client:
    text_input = TtsTextInput()
    text_input.append("欢迎使用，")

    def feed_llm_text():
        # 在真实后端中，这里逐段读取 LLM 输出。
        text_input.append("这是双向流式语音服务。")
        text_input.finish()

    producer = threading.Thread(target=feed_llm_text)
    producer.start()
    for pcm_chunk in client.synthesize(text_input):
        send_pcm_s16le_24000_mono_to_browser(pcm_chunk)
    producer.join()

    # audio.done 后可在同一 WebSocket 上继续下一段。
    for pcm_chunk in client.synthesize(["第二段播报。"]):
        send_pcm_s16le_24000_mono_to_browser(pcm_chunk)
```

当浏览器用户打断播报时，从另一个线程调用 `client.cancel_active()`。它会取消仍在等待 LLM 文本的
`TtsTextInput`、发送带当前 `utterance_id` 的 `response.cancel`，并让 `synthesize()` 在收到
`response.cancelled` 后正常结束。此后可在同一客户端上开始下一次 `synthesize()`；调用方还应
清空浏览器播放器中已经排队但尚未播放的 PCM。

`synthesize()` 在后台持续消费 `TtsTextInput`，同时在调用线程产出音频，因此上游 LLM 尚未结束
文本输出时，CPU 后端就可以收到并转发首批 PCM。`TtsTextInput` 是有界且可取消的；流式调用必须
使用它，已完整保存在内存中的短文本也可直接传 `list` 或 `tuple`。每次调用只对应一个 utterance；
必须把返回迭代器消费到 `audio.done` 或 `response.cancelled` 才能开始下一次调用。服务端错误、
超时或协议错会关闭当前连接，调用方应新建
客户端连接；不要自动重放已经开始的 utterance，以免重复播报。

同一客户端的并发 `synthesize()` 会被拒绝。如果调用方提前停止消费或关闭返回迭代器，客户端会
关闭当时的 WebSocket、取消 `TtsTextInput` 并等待发送线程退出；旧请求不会留下等待文本的后台
线程，也不能把迟到文本写进随后建立的新会话。连接建立时客户端还会核对固定模型、音色和 PCM
元数据。

GPU 端只允许一个活跃 TTS WebSocket。CPU 后端应集中管理这条连接并按业务优先级排队，不要让
每个浏览器各自直连 GPU。`close()` 在空闲状态发送 `session.close`；上下文管理器会自动调用它。
