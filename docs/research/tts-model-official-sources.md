# TTS 候选模型：BI-V150 环境与官方资料核实

核实日期：2026-09-11。依据模型发布方的一手资料、仓库内 BI150 厂商资料及本机只读检查。本次没有下载权重、安装依赖或启动 TTS 模型；本文中的兼容性和显存结论只区分“厂商已验证”与“需要 POC”，不把 NVIDIA/CUDA 的公开结果当作 BI-V150 实测。

## 结论

本项目首版推荐 **`iic/CosyVoice-300M-Instruct`**。原因不是它在公开指标上最新，而是它是候选中唯一同时满足以下条件的真正本地模型：

- 仓库 [BI150 厂商模型清单](../../bi150/README.md#L130)明确将它列为 Transformers 路径，并在 MR/BI150 一栏标记支持；[厂商样例](../../bi150/README.md#L644)给出了本机权重目录、依赖和运行命令。
- 共享盘已经有完整权重 `/share/fshare/common/models/CosyVoice/CosyVoice-300M-Instruct`，约 5.4 GiB；其名称标明 300M，Hugging Face 模型元数据和官方仓库均标记 Apache-2.0。[官方模型页](https://huggingface.co/FunAudioLLM/CosyVoice-300M-Instruct)、[官方代码许可证](https://github.com/QwenAudio/CosyVoice/blob/main/LICENSE)
- 本地检查点提供中文女、中文男、粤语女、日语男、英语女、英语男、韩语女 7 个固定音色；Instruct 模式支持自然语言风格描述以及笑声、呼吸、强调等控制。它适合首版“固定音色 + 中文为主 + 可控风格”的业务。[官方使用示例](https://github.com/QwenAudio/CosyVoice/blob/main/example.py)
- 官方实现具备 `stream=True` 的音频分块生成路径；厂商随镜像提供的 FastAPI 样例虽然返回 `StreamingResponse`，但没有打开模型级 `stream=True`，正式服务需要自己的薄封装显式启用分块、鉴权、限流和健康检查，不能原样暴露厂商 WebUI 或样例接口。

如果业务明确要求**任意参考音频克隆音色**，主选应改为 **`FunAudioLLM/Fun-CosyVoice3-0.5B-2512` POC**。CosyVoice-300M-Instruct 使用预置音色，不是零样本克隆模型；CosyVoice 3 则支持跨语种零样本克隆、9 种语言、18 种以上中文方言/口音、指令控制和双向流式。官方也明确推荐 CosyVoice 3 获得更好的效果。[CosyVoice 官方说明](https://github.com/QwenAudio/CosyVoice#highlight)、[CosyVoice 3 模型页](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512)

CosyVoice 3 **不属于本机厂商已验证项**。它比 300M-Instruct 更值得做质量升级，但必须先在独立环境完成 CoreX 算子兼容、首包延迟、RTF、显存峰值和并发验收。若 CosyVoice 3 适配失败，`CosyVoice2-0.5B` 是同一代码栈下的次选 POC；若不需要克隆，只需要更现代的固定中文音色，`Qwen3-TTS-12Hz-0.6B-CustomVoice` 也值得后续 POC，但本机当前名为 `Qwen3-TTS-12Hz-1.7B-Base` 的目录实际是 `Qwen3ASRForConditionalGeneration`，不是可用 TTS 权重。

`edge-tts-zh` 不应作为本 GPU 算法服务。它只是访问微软 Edge 在线 TTS 的客户端：官方 README 直接称其为 Microsoft Edge **online** TTS，源码固定连接 `wss://speech.platform.bing.com/...`；厂商目录中的 `data_process.py` 也只调用 `edge_tts.Communicate`，所谓 `model.onnx` 只有 860 bytes 且没有被推理脚本使用。因此它不在本机执行模型、不占 GPU 显存、离线不可用，并受外网、微软端点变化和限流影响。[edge-tts 官方说明](https://github.com/rany2/edge-tts/blob/master/README.md)、[服务端点源码](https://github.com/rany2/edge-tts/blob/master/src/edge_tts/constants.py)

## 本机资源与厂商支持边界

`ixsmi` 快照显示两张 Iluvatar BI-V150 均为 32768 MiB：

| 设备 | 已用 / 空闲 | 当前主要进程 |
| --- | --- | --- |
| GPU 0 | 11892 / 32768 MiB，约 20876 MiB 空闲 | ASR vLLM 7732 MiB、ASR Python 1634 MiB、RAG 2218 MiB、YOLO 192 MiB |
| GPU 1 | 27052 / 32768 MiB，约 5716 MiB 空闲 | VLM vLLM 26968 MiB |

显存值来自 2026-09-11 本机瞬时快照，会随请求和缓存变化。GPU 1 余量过小，TTS 首轮应放在 GPU 0，从单并发开始，并测量与 ASR、RAG、YOLO 同时工作时的峰值；不能只用磁盘权重大小推算显存。主机有约 503 GiB 内存，因此 CPU 内存目前不是首要约束。

实际软件基线为 Python 3.10.18、`torch 2.7.1+corex.4.4.0`、`torchaudio 2.7.1+corex.4.4.0`、`transformers 4.57.6`、`vllm 0.17.0+corex.4.5.0.rc.11.20260701`。不得用上游 CUDA wheel 覆盖这些厂商构建。

厂商清单中的 TTS 相关条目只有 `CosyVoice-300M-Instruct` 和 `edge-tts-zh`，二者均被打勾；但这两个勾的含义不同：前者有本地权重和本卡推理适配代码，后者只是 CPU 网络客户端成功访问微软在线服务。厂商目录中的 CosyVoice 推理脚本明确关闭 memory-efficient SDP 与 flash SDP，改用 math SDP；其外层依赖说明还记录了 ONNX Runtime 算子版本问题。这些是本卡适配证据，也是后续部署应固定厂商源码快照和依赖、避免直接跟随 CosyVoice `main` 的原因。[厂商音频样例](../../bi150/README.md#L633)

共享盘检查结果：

| 路径 | 磁盘占用 | 判断 |
| --- | ---: | --- |
| `/share/fshare/common/models/CosyVoice/CosyVoice-300M-Instruct` | 约 5.4 GiB | 完整本地权重，含 PyTorch、JIT、ONNX 制品及 7 个预置音色 |
| `/share/fshare/common/models/2Noise/chatTTS` | 约 1.1 GiB | ChatTTS 旧式 `.pt` 权重，需另行核对与当前官方代码版本 |
| `/share/fshare/common/models/Qwen/Qwen3-TTS-12Hz-1.7B-Base` | 约 8.7 GiB | **目录名错误**；`config.json` 的架构为 `Qwen3ASRForConditionalGeneration`、任务为 ASR，不得当作 TTS 使用 |
| CosyVoice 2/3、F5-TTS、Fish Speech S2 | 未发现 | 若选择 POC，需下载并固定模型 revision |

## 候选对比

| 候选 | 语言、音色与控制 | 流式能力 | 许可证 | BI150/CoreX 判断 |
| --- | --- | --- | --- | --- |
| `CosyVoice-300M-Instruct` | 300M；本地检查点含 7 个预置音色，中文为主要用法；支持自然语言人设/风格指令以及强调、笑声、呼吸等控制。不提供任意参考音频的零样本克隆。 | 官方生成 API 有 `stream=True` 分块路径；首包和 RTF 未在当前运行负载下实测。 | 代码和模型元数据均为 Apache-2.0。[模型页](https://huggingface.co/FunAudioLLM/CosyVoice-300M-Instruct) | **厂商明确验证，首选**。共享盘已有权重和厂商适配脚本；仍需在现有四路 GPU 服务并存状态下实测。 |
| `CosyVoice2-0.5B` | 0.5B；中文、英语、日语、韩语及粤语、四川话、上海话、天津话、武汉话等；支持跨语种/混合语种零样本克隆和 `inference_instruct2` 风格控制。 | 官方称双向流式，首包可低至 150 ms；这是发布方环境结果。[官方仓库](https://github.com/QwenAudio/CosyVoice#highlight) | Apache-2.0。[模型页](https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B) | **需 POC**。官方支持 vLLM 0.11.x+，本机版本号满足但属于 CoreX 分支，不能据此推定自定义模型注册与算子兼容。[vLLM 说明](https://github.com/QwenAudio/CosyVoice#vllm-usage) |
| `Fun-CosyVoice3-0.5B-2512` | 0.5B；9 种语言、18+ 中文方言/口音；支持跨语种零样本克隆、拼音/音素发音修补、情绪、语速、音量等指令。官方评测较 CosyVoice 2 提升中文内容一致性和音色相似度。 | 文本输入和音频输出均可流式，发布方称最低约 150 ms。[官方说明](https://github.com/QwenAudio/CosyVoice#key-features) | Apache-2.0。[模型页](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512) | **质量升级首选 POC**。官方 `main` 依赖锁定上游 torch 2.3.1、Transformers 4.51.3，并面向 CUDA/ONNX Runtime/TensorRT；与 CoreX torch 2.7.1 不同，须独立环境复用厂商 torch，不能照装 requirements。[官方依赖](https://github.com/QwenAudio/CosyVoice/blob/main/requirements.txt) |
| `Qwen3-TTS-12Hz-0.6B-CustomVoice` | 0.6B；10 种语言；9 个固定高质量音色，其中包含普通话女声/男声、北京话男声和四川话男声；支持可选自然语言风格指令。声线设计和参考音频克隆分别使用 VoiceDesign 与 Base 变体。 | 模型架构支持流式，发布方报告端到端最低 97 ms。Qwen3-TTS 仓库中的 vLLM 小节仍写“仅离线”，但更新更晚的 vLLM-Omni 官方文档已经提供 1.7B 变体的 OpenAI 兼容在线服务、PCM 和 WebSocket 流式接口；本机未安装该运行栈。[官方仓库](https://github.com/QwenLM/Qwen3-TTS#released-models-description-and-download)、[vLLM-Omni 在线服务](https://github.com/vllm-project/vllm-omni/blob/main/docs/user_guide/examples/online_serving/text_to_speech.md#qwen3-tts) | Apache-2.0。[模型页](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice) | **后续 POC**。官方包支持 Python 3.10，锁定 Transformers 4.57.3，与本机较接近；但厂商清单无此架构，且本机没有正确权重。上游 vLLM-Omni 的在线能力也不能证明 CoreX vLLM 可直接运行。[官方依赖](https://github.com/QwenLM/Qwen3-TTS/blob/main/pyproject.toml) |
| `F5-TTS v1 Base` | 官方公开基座约 0.3B，主要为中英文；通过参考音频实现零样本音色克隆，支持多风格/多说话人分段生成。没有 CosyVoice 3 那样完整的方言、发音修补和自由指令能力。 | 官方提供 chunk inference 和 TCP socket 音频块示例；它是非自回归模型按文本块生成，首包取决于首个文本块推理，不等同逐字符双向流式。[官方仓库](https://github.com/SWivid/F5-TTS)、[socket 服务](https://github.com/SWivid/F5-TTS/blob/main/src/f5_tts/socket_server.py) | 代码 MIT；公开预训练权重因 Emilia 数据为 CC BY-NC 4.0，不能直接用于商业服务。[许可证说明](https://github.com/SWivid/F5-TTS#license) | **不列入当前主线**。BI150 未验证，官方 Docker/性能路径面向 NVIDIA；许可证也会限制商业业务。 |
| `Fish Audio S2-Pro` | Slow AR 4B + Fast AR 400M；约 50 种语言；10–30 秒参考音频克隆、原生多说话人/多轮和自由文本局部情绪控制。 | 官方 SGLang 路径在单张 H200 报告 RTF 0.195、首音频约 100 ms；不能外推到 BI150。[官方说明](https://github.com/fishaudio/fish-speech/blob/main/docs/en/index.md) | Fish Audio Research License；商业用途必须另签书面许可。[官方许可证](https://github.com/fishaudio/fish-speech/blob/main/LICENSE) | **排除当前机器**。官方要求至少 24 GB 显存并依赖 torch 2.8.0、CUDA/SGLang；GPU 0 当前空闲不足 24 GB，GPU 1 仅余约 5.7 GB。[推理要求](https://speech.fish.audio/inference/)、[依赖](https://github.com/fishaudio/fish-speech/blob/main/pyproject.toml) |
| `ChatTTS` | 参数规模官方未明确标注；中文、英语对话，支持随机/复用说话人 embedding，笑声、停顿和口语程度控制，当前官方代码已有分块生成。它没有 CosyVoice 3 同等级的跨语种克隆与开放式指令控制。 | 官方路线图已标记 streaming 完成，`infer(..., stream=True)` 返回生成器；官方 FAQ 称 30 秒音频至少需 4 GB 显存，均不是 BI150 实测。[官方仓库](https://github.com/2noise/ChatTTS) | 代码 AGPLv3+；模型 CC BY-NC 4.0，仅限教育研究用途。[许可证说明](https://github.com/2noise/ChatTTS#licenses) | **不列入当前主线**。虽然共享盘有权重，官方可选 vLLM 仍写死 0.2.7，与本机 CoreX vLLM 0.17.0 相距很大；许可证也不适合一般业务服务。 |
| `edge-tts` / 厂商 `edge-tts-zh` | 微软在线音色；客户端可调 voice、rate、volume、pitch，不具备本地模型权重或本地音色克隆。 | 从微软在线 WebSocket 接收 MP3 音频块。 | Python 库大部分为 LGPLv3；微软在线服务的使用条件不能由该库许可证替代。[代码许可证](https://github.com/rany2/edge-tts/blob/master/LICENSE) | **排除**。不是 GPU 本地推理；依赖互联网和第三方消费端点，无法纳入本机显存与模型耗时口径。 |

参数量只采用模型名或发布方明确标注的数据；ChatTTS 官方没有明确给出参数量，因此没有用文件大小反推。CosyVoice、Qwen3-TTS、Fish Speech 的“最低首包”均是发布方在其他硬件/软件条件下的结果，只能作为功能存在的证据，不能成为本项目 SLA。

## CosyVoice 300M 与 CosyVoice 2/3 的取舍

`CosyVoice-300M-Instruct` 的优势是当前可落地性：厂商验证、权重现成、固定音色适合稳定 API、Apache-2.0。它的限制也应写入接口契约：可选音色只能来自服务端白名单；Instruct 不是用户上传参考音频克隆；初始采样率为 22050 Hz；流式变速在本地旧实现中受限制。

CosyVoice 2/3 的优势是业务能力：参考音频克隆、更多方言、多语种、双向流式和更完整的自然语言控制。CosyVoice 3 是发布方当前推荐版本，功能与公开评测都优于 v1；一旦本机 POC 通过，它比继续扩展 v1 更适合作为长期模型。它的风险主要来自运行栈而非参数规模：官方依赖、ONNX Runtime、Triton/TensorRT 和 vLLM 均以 NVIDIA/CUDA 为主，本机必须避开上游 CUDA wheel并验证 CoreX 后端。

因此建议分两阶段：首版用 300M-Instruct 把统一网关、鉴权、HTTP chunked 音频返回、监控和 CPU 后端调用链做通；同时用同一批中文文本对 CosyVoice 3 做离线 POC。若 CosyVoice 3 在本机达到资源和延迟门槛，再保持公开 API 不变替换后端模型。

## 建议的首轮 POC 与验收口径

首轮只启动单个 TTS worker，绑定 GPU 0 和本地回环地址；服务通过现有 NGINX 统一端口与 API key 暴露 `POST /tts/v1/audio/speech`。响应建议采用 HTTP chunked 原始 PCM16 或 WAV 流，并继续关闭 NGINX 响应缓冲。模型服务不要直接监听公网。

部署前后至少记录：

1. **模型可用性**：进程健康、首条中文输出非空且可解码；数字、英文缩写、中英混合、标点、长句和非法参数有确定行为。
2. **服务显存**：空闲基线、模型加载后驻留 MiB、单请求峰值 MiB；同时压测 ASR/RAG/YOLO，避免把 vLLM 预留或共享子进程重复计数。
3. **TTS 服务耗时**：建议将“GPU 端首音频块延迟”作为主指标，另记录完整合成耗时、生成音频时长和 RTF（完整合成耗时 / 音频时长）。只有完整响应而没有首块时间，无法评价流式体验。
4. **流式质量**：首块是否是真实可播放音频、块间是否爆音/断裂、客户端取消后 GPU 工作是否停止、NGINX 是否即时转发、长文本是否持续输出。
5. **并发与共存**：从并发 1 开始，再测 2/4；记录首块 p50/p95、RTF p50/p95、错误率、峰值显存，以及 TTS 请求对实时 ASR 和 YOLO 延迟的影响。
6. **音质与控制**：用固定业务文本盲听清晰度、自然度、音色一致性、指令遵循；若做克隆，必须另测参考音频长度、噪声、转录不一致和跨语种场景。

CosyVoice-300M-Instruct 的首轮目标是证明现有厂商路径能在四路服务并存时稳定流式输出，而不是先追求高并发。CosyVoice 3 的升级门槛应至少包括：功能不回退、显存可共存、首包/RTF 达标、连续运行无泄漏，并通过同一批中文业务文本的人工听测。

## 一手来源

- [本项目 BI150 厂商模型清单与音频样例](../../bi150/README.md#L130)
- [CosyVoice 官方仓库](https://github.com/QwenAudio/CosyVoice)与[Apache-2.0 许可证](https://github.com/QwenAudio/CosyVoice/blob/main/LICENSE)
- [CosyVoice-300M-Instruct](https://huggingface.co/FunAudioLLM/CosyVoice-300M-Instruct)、[CosyVoice2-0.5B](https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B)、[Fun-CosyVoice3-0.5B-2512](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512)
- [edge-tts 官方仓库](https://github.com/rany2/edge-tts)、[PyPI 项目页](https://pypi.org/project/edge-tts/)
- [Qwen3-TTS 官方仓库](https://github.com/QwenLM/Qwen3-TTS)及[0.6B CustomVoice 模型页](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice)
- [F5-TTS 官方仓库](https://github.com/SWivid/F5-TTS)
- [Fish Speech 官方仓库](https://github.com/fishaudio/fish-speech)及[部署文档](https://speech.fish.audio/install/)
- [ChatTTS 官方仓库](https://github.com/2noise/ChatTTS)及[官方模型页](https://huggingface.co/2Noise/ChatTTS)
