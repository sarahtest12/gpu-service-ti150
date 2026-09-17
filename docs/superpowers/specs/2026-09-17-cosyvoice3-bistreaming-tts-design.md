# Fun-CosyVoice3 双流 TTS 设计

日期：2026-09-17

## 目标

将现有 `CosyVoice-300M-Instruct` 单次 HTTP TTS 服务替换为
`FunAudioLLM/Fun-CosyVoice3-0.5B-2512` 双流服务。CPU Web 后端与 GPU 主机建立一个
WebSocket，会话内持续追加文本；GPU 在文本尚未结束时即可持续返回可播放的 PCM 音频。

本次切换完成后，TTS 不再提供公开 HTTP 合成和音色列表接口。内部 HTTP 健康检查与 Prometheus
指标继续保留，供本机网关管理器和监控服务使用。

## 已确定的选择

- 使用 `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` 的标准 `llm.pt`，不加载 `llm.rl.pt`。
- 使用 CosyVoice 原生 PyTorch `Generator` 文本输入和 `stream=True` 音频输出。
- `load_vllm=false`：官方 vLLM 路径不接受文本 `Generator`，不能满足严格双流。
- `load_trt=false`：BI-V150/CoreX 不提供 NVIDIA TensorRT 运行时。
- 不使用 JIT；CosyVoice3 构造器也不提供 CosyVoice v1 的 JIT LLM 加载路径。
- 首选 CoreX FP16。若真实 POC 证明模型在 FP16 下存在不受支持的算子或数值错误，可以改用
  原生 PyTorch FP32；不得以牺牲文本输入双流为代价切换到 vLLM。
- GPU 设备保持为 0，并发限制保持为一个活跃生成会话。
- 首版只有一个固定音色 `aishell3-female`，参考音频来自 Apache-2.0 许可的 AISHELL-3 普通话
  女声数据。
- 公开 TTS 业务入口只有 `WSS /tts/v1/realtime`。

## 模型和运行环境

模型快照、CosyVoice 源码和 Python 依赖都必须锁定版本及 SHA-256。模型目录使用
`/share/fshare/common/models/CosyVoice/Fun-CosyVoice3-0.5B-2512`；服务启动时检查
`cosyvoice3.yaml`、`llm.pt`、`flow.pt`、`hift.pt`、`campplus.onnx`、
`speech_tokenizer_v3.onnx` 和文本 tokenizer 资源。

CosyVoice 源码放入 TTS 服务自己的运行目录，不修改现有 CosyVoice v1 厂商目录。bootstrap 从官方
仓库的固定 commit 获取源码，并应用仓库内保存的最小 CoreX 补丁。补丁只负责让 speech tokenizer
使用本机实际存在的 ONNX Runtime `CPUExecutionProvider`；PyTorch 模型仍在 GPU 0 上运行。
bootstrap 不安装通用 CUDA、NVIDIA TensorRT、上游 vLLM、`onnxruntime-gpu`，也不覆盖
CoreX 的 torch/torchaudio。

启动检查必须验证：CoreX torch 来源和版本、CPU ONNX provider、模型文件、源码及补丁校验和、
固定音色清单、24 kHz 输出采样率和可用显存。任何检查失败时服务不得监听端口。

## 固定音色资产

仓库保存音色 manifest，不保存来源不明的示例音频。manifest 固定 AISHELL-3 数据集 revision、
说话人 ID、音频文件 ID、准确文字、性别、来源 URL、Apache-2.0 许可证 URL、原始文件 SHA-256
和派生文件 SHA-256。

实现阶段从 AISHELL-3 官方发布或其官方 Hugging Face 数据集镜像中选择一名普通话女性说话人。
候选录音必须满足以下自动检查：单声道、无削波、有效语音约 5 至 10 秒、头尾静音合计不超过
1 秒、转写完整，并且没有可闻环境噪声。若单条录音不足 5 秒，只能拼接同一说话人的相邻完整
句子，并在 manifest 中逐条记录来源和文字。

bootstrap 按 manifest 下载已固定的源文件，确定性地转为 24 kHz、单声道 PCM WAV，校验派生
SHA-256 后写入忽略提交的 `tts_service/runtime/voices/aishell3-female/`。服务启动时调用一次
CosyVoice `add_zero_shot_spk` 提取并缓存 prompt，后续每个会话只引用同一份缓存；不得在请求间
重新随机选择音频或说话人。

AISHELL-3 的 Apache-2.0 数据许可会记录在交付文档中。该公开数据用于首版技术音色；后续替换为
项目自行录制且取得明确合成语音授权的音色时，只替换 manifest 和运行时资产，不改变协议。

## WebSocket 契约

外部地址为 `wss://GPU_HOST:8443/tts/v1/realtime`。CPU Web 后端在握手头中携带
`Authorization: Bearer <GPU_API_KEY>`；网关验证共享 key 后，覆盖为 TTS 内部 key 再转发到
`127.0.0.1:8004/realtime`。调用方不能直接使用内部 key。

握手成功后，服务先发送：

```json
{
  "type": "session.created",
  "session_id": "tts_opaque_id",
  "model": "fun-cosyvoice3-0.5b-2512",
  "voice": "aishell3-female",
  "audio": {
    "format": "pcm_s16le",
    "sample_rate_hz": 24000,
    "channels": 1
  }
}
```

客户端消息只有三种：

```json
{"type":"input.text","text":"欢迎使用"}
{"type":"input.done"}
{"type":"session.close"}
```

- `input.text` 追加当前 utterance 的文本。每条最多 1024 个 Unicode 字符，每个 utterance 累计
  最多 4096 个字符；空白、NUL 和 tokenizer 控制序列无效。
- 第一条 `input.text` 建立一个 utterance 并立即启动原生 PyTorch 双流生成。服务无需等待
  `input.done` 才能返回音频；模型积累足够文本 token 后即可产生首个音频块。
- `input.done` 关闭当前文本生成器。发送后不得再向该 utterance 追加文本。
- 服务完成该 utterance 并发送 `audio.done` 后，连接回到空闲状态，可继续发送下一条
  `input.text`。同一连接不允许两个 utterance 并行。
- `session.close` 只在空闲状态执行优雅关闭；直接关闭 WebSocket 也必须释放服务端状态。

服务为每个 utterance 先发送 JSON 控制事件，再发送二进制 PCM：

```json
{"type":"audio.start","utterance_id":"utt_opaque_id"}
```

随后是一个或多个二进制 PCM S16LE 帧，最后发送：

```json
{"type":"audio.done","utterance_id":"utt_opaque_id"}
```

PCM 帧边界只有传输意义，客户端必须将其视为连续的 24 kHz、单声道 PCM 字节流。音频可能在
`input.done` 前到达；这项行为必须由真实模型验收测试证明。极短文本可能直到更多文本或
`input.done` 后才产生音频，协议不承诺每个输入 chunk 都立即对应一个音频 chunk。

错误使用以下结构：

```json
{
  "type": "error",
  "code": "invalid_state",
  "message": "input.text is not allowed after input.done",
  "fatal": false
}
```

可恢复的格式、长度和空 utterance 错误设置 `fatal=false`，清理当前 utterance 后允许继续使用
连接。鉴权失败、内部推理失败、输出队列阻塞超时及协议无法恢复的状态设置 `fatal=true`，发送
错误后关闭连接。错误消息不包含请求文本、参考音频路径、堆栈或内部 key。

网关与服务都只允许一个活跃 TTS WebSocket。占用时新的握手返回 429。单条 WebSocket 消息上限
16 KiB，连接读取空闲超时为 3600 秒；活跃 utterance 等待下一段文本的最长时间为 300 秒，超时
后以 `input_timeout` 结束该连接。

## 服务内部结构

FastAPI 负责鉴权、WebSocket 状态机、健康检查和指标，模型推理在独立工作线程执行，不能阻塞
事件循环。每个 utterance 使用两个有界队列：

1. WebSocket reader 将 `input.text` 放入文本队列；同步 Python generator 从该队列读取，
   `input.done` 放入唯一 EOF 标记。
2. 模型线程调用 `inference_zero_shot(text_generator, ..., stream=True)`，将 PCM 字节放入输出
   队列；WebSocket writer 按顺序发送控制事件和二进制帧。

两个队列都采用背压，不允许无限累积文本或音频。客户端断开或 fatal error 时设置取消标志、
关闭文本 generator，并关闭厂商输出 generator。若厂商实现不能立即取消已经开始的 GPU 生成，
服务在后台排空该 generator 以释放 UUID 缓存；在清理完成前并发槽不释放。

日志只记录 session ID、utterance ID、状态、耗时、字节数和异常类型，不记录输入文本、prompt
转写或音频内容。

## 监控口径

保留 `tts_time_to_first_token_seconds` Prometheus 直方图，每个完成或失败前已经产出 token 的
utterance 最多记录一次。起点是第一批规范化文本 token 被提交给 GPU 的
`inference_bistream`，终点是第一个语音 token 在 GPU 服务进程可见。该指标排除等待客户端输入、
文本队列等待、PCM 解码、网络和播放器缓冲，也不等同于客户端听到声音的延迟。

内部 `GET /health` 和 `GET /metrics` 继续要求 TTS 内部 key，只监听 loopback。监控服务继续直接
访问内部接口；统一网关不再公开 `/tts/health/ready` 或任何 TTS HTTP 路径。

## 网关与契约文件

NGINX 仅增加精确匹配的 `/tts/v1/realtime` WebSocket location，设置 Upgrade/Connection、内部
Authorization、连接限制、3600 秒读写超时并关闭代理缓冲。删除以下公开 location：

- `/tts/v1/audio/speech`
- `/tts/v1/audio/voices`
- `/tts/health/ready`

OpenAPI 保留 WebSocket 握手的 GET/101 描述，并通过 `x-websocket-contract` 指向新增的
`contracts/tts-websocket.md`。该文档完整描述消息、二进制音频、状态机、限制和错误。现有
TTS HTTP schema、响应和示例从 OpenAPI 及 `contracts/README.md` 删除。

CPU 示例客户端改用 WebSocket：连接一次、验证 `session.created` 音频元数据、分批发送文本、
发送 `input.done`、播放或保存收到的连续 PCM，并在 `audio.done` 后复用连接。HTTPX TTS 合成
客户端和旧 HTTP 示例删除。

## 测试和验收

代码改动遵循测试先行。CPU 单元测试覆盖：

- WebSocket 鉴权和 `session.created`。
- 文本 generator 在 `input.done` 前得到多个文本 chunk。
- 服务在 `input.done` 前发送首个二进制音频帧。
- PCM 转换、消息顺序、连接内多个顺序 utterance。
- 空文本、超长文本、未知消息、重复 `input.done`、错误状态和并发限制。
- 断连、模型异常、队列超时后 generator 清理和并发槽释放。
- 日志不泄露文本、prompt 或凭据。
- 网关只生成 WebSocket location，正确覆盖内部 key，并不再生成三个 TTS HTTP location。
- OpenAPI 和独立 WebSocket 契约中的路径、模型名、采样率及限制一致。

真实 BI-V150 验收按以下顺序执行：

1. 在不切换公开路由时下载并校验模型、源码和 AISHELL-3 固定音色。
2. 验证 CoreX FP16 完整文本合成；记录启动峰值和稳定显存。
3. 每 50 至 100 ms 向 Python generator 追加中文，证明 `input.done` 前已经得到 PCM。
4. 通过内部 WebSocket 连做至少三个 utterance，确认音色一致、状态可复用且 GPU 缓存清理。
5. 通过统一 `wss://.../tts/v1/realtime` 验证鉴权、二进制音频和网关长连接。
6. 记录首语音 token、首 PCM、RTF、稳定显存和生成峰值；监控快照必须显示新 TTS 进程及最近
   60 秒首 token 指标。

验收通过后才停止旧 CosyVoice v1 服务并重新加载网关。切换是一次性替换：公开 HTTP TTS 路由
不会与 WebSocket 路由并存。如果新模型在 CoreX 上无法完成完整合成或严格双流验证，保持旧服务
和旧网关配置运行，并报告具体算子、依赖或性能阻塞，不发布一个退化成单向流的新接口。

