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
from tts_client import TtsRealtimeClient

with TtsRealtimeClient(
    "https://GPU_HOST:8443/tts",
    api_key=os.environ["GPU_API_KEY"],
    ca_file="/path/to/server.crt",
) as client:
    def llm_text_chunks():
        yield "欢迎使用，"
        yield "这是双向流式语音服务。"

    for pcm_chunk in client.synthesize(llm_text_chunks()):
        send_pcm_s16le_24000_mono_to_browser(pcm_chunk)

    # audio.done 后可在同一 WebSocket 上继续下一段。
    for pcm_chunk in client.synthesize(["第二段播报。"]):
        send_pcm_s16le_24000_mono_to_browser(pcm_chunk)
```

`synthesize()` 在后台持续消费文本迭代器，同时在调用线程产出音频，因此上游 LLM 尚未结束文本
输出时，CPU 后端就可以收到并转发首批 PCM。每次调用只对应一个 utterance；必须把返回迭代器
消费到 `audio.done` 才能开始下一次调用。服务端错误、超时或协议错会关闭当前连接，调用方应新建
客户端连接；不要自动重放已经开始的 utterance，以免重复播报。

同一客户端的并发 `synthesize()` 会被拒绝。如果调用方提前停止消费或关闭返回迭代器，客户端会
关闭当时的 WebSocket；仍在等待上游文本的旧发送线程只持有旧连接，不能把迟到文本写进随后建立
的新会话。连接建立时客户端也会核对固定模型、音色和 PCM 元数据。

GPU 端只允许一个活跃 TTS WebSocket。CPU 后端应集中管理这条连接并按业务优先级排队，不要让
每个浏览器各自直连 GPU。`close()` 在空闲状态发送 `session.close`；上下文管理器会自动调用它。
