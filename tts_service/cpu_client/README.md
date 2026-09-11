# CPU 后端调用流式 TTS

此目录可以独立复制到 CPU Web 后端，不需要 GPU、CoreX 或 torch。安装依赖，复制
`config.gateway.example.json` 为 `config.gateway.json`，把 `GPU_HOST` 替换为 GPU 服务器地址，
并放置覆盖该地址的可信证书。本机开发证书只覆盖 `localhost/127.0.0.1`。

通过安全配置注入与其他算法相同的 `GPU_API_KEY`。浏览器不应持有此 key；CPU 后端调用 GPU，
再按业务权限向浏览器转发音频。不要复制 GPU 上的 TTS 内部 key 或 TLS 私钥。

```bash
python -m pip install -r requirements.txt
GPU_API_KEY='统一公开key' python demo.py \
  --config config.gateway.json \
  --text '欢迎使用语音服务。' \
  --output output.wav
```

Python 调用：

```python
import os
from tts_client import TtsClient

with TtsClient(
    "https://GPU_HOST:8443/tts/v1",
    api_key=os.environ["GPU_API_KEY"],
    ca_file="/path/to/server.crt",
) as client:
    with client.stream(
        "欢迎使用语音服务。",
        voice="中文女",
        instructions="用自然、亲切的语气播报。",
    ) as chunks:
        for pcm_chunk in chunks:
            consume_pcm_s16le_22050_mono(pcm_chunk)
```

`stream()` 返回连续的 22050 Hz 单声道 PCM S16LE 字节。HTTPX 提供的每个 `chunk` 大小不固定；
播放器应把它们视为同一连续流。`demo.py` 先把 PCM 放入临时文件，知道完整长度后再写 WAV 头，
因此不会产生长度错误的 WAV。

客户端验证 TLS 和音频格式头，关闭环境代理、重定向和自动重试。超时或 HTTP 错误会抛出脱敏的
`RuntimeError`。合成请求不能安全自动重试，否则可能重复播报。当前服务只允许 1 个活跃请求；
CPU 后端应按业务优先级排队，并在前端展示忙碌状态。
