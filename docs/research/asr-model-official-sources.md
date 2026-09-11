# ASR 候选模型：BI-V150 环境与官方资料核实

核实日期：2026-09-10。依据模型发布方的一手资料、仓库内 BI150 厂商资料及本机检查。
选型结论形成后，项目已按结论完成首轮部署；下面单列实测状态，候选对比仍保留选型时的官方边界。

## 结论

产品现在明确要求**实时增量输出**，因此 Belle 不再适合作为主选。中文、英语、日语和中文方言为主要业务时，`FunAudioLLM/Fun-ASR-Nano-2512` 是本项目首选：它只有 800M，官方提供含动态 VAD、热词和实时 partial/final 输出的 WebSocket 服务，协议与前端字幕交互也比 Qwen3-ASR 当前的最小演示更完整。它不在 BI150 厂商清单中，官方 vLLM 验证也基于 NVIDIA/CUDA，因此生产容量仍以本机压测为准。

`Qwen/Qwen3-ASR-1.7B` 保留为第二个 POC：本机已经有权重，CoreX 定制 vLLM 也包含其离线和 realtime 代码路径；它覆盖 30 种语言和 22 种中文方言，适合更广的多语言业务。它的官方 SDK 流式模式以约 2 秒音频块累计重解码，仅支持 vLLM，每个状态表示一条音频流，并且不支持批处理和时间戳；官方 Web 演示使用带 session id 的 HTTP `start/chunk/finish`，没有提供 Fun-ASR-Nano 那样的 VAD 分句 WebSocket 服务。因此，在本项目当前“中文实时字幕 + 统一网关”的需求下，Fun-ASR-Nano 的服务能力更贴合；在“多语言覆盖 + 尽量复用本地权重”的优先级下，Qwen3-ASR 更合适。

如果只做**中文音频文件转写**，`BELLE-2/Belle-whisper-large-v3-zh` 仍是兼容风险最低的选择：它是本地厂商清单中唯一明确标记 MR/BI150 支持的 ASR 模型。但它没有官方增量流式接口，不能满足当前主需求。

`openai/whisper-large-v3` 不作为本机首选：它和 Belle 是同一规模，具备更广的多语言能力，但也没有原生流式能力，而且本地厂商清单没有明确列出它。业务以中文为主时，Belle 同时拥有中文微调和厂商适配依据。

## 部署状态更新

项目已固定 FunASR revision `e42443f55971d0c804dcf2973fdd2e6e09bd5611`，在独立环境中复用本机
CoreX vLLM 0.17.0，并从 ModelScope 固定原始检查点。GPU 0 上的音频编码器、服务端 FSMN-VAD
和 vLLM Qwen3-0.6B 解码器均已加载。经统一 TLS 入口回放 5.616 秒样例时连续收到 partial，
最终文本与直接推理一致；真实协议和显存结果见 [`../../asr_service/docs/validation.md`](../../asr_service/docs/validation.md)。
这证明当前单路链路兼容，不替代长句、噪声、业务词和 4 路并发验收。

## 本机环境与厂商支持边界

本次 `ixsmi` 快照中，两张 Iluvatar BI-V150 均为 32768 MiB：GPU 0 已用 2502 MiB，运行 BGE-M3 和 YOLO；GPU 1 已用 27052 MiB，主要运行 Qwen3.5-9B VLM。因此 ASR 应优先放在 GPU 0，并在与 YOLO、RAG 并存时实测峰值显存与延迟。

实际环境为 Python 3.10、`torch 2.7.1+corex.4.4.0`、`transformers 4.57.6`、`vllm 0.17.0+corex.4.5.0.rc.11.20260701` 和 `ixformer 0.7.0+corex.4.5.0.rc.11.20260701`；`ffmpeg`、librosa 和 SoundFile 已安装，`qwen-asr` 与 `openai-whisper` 未安装。

仓库[厂商模型清单](../../bi150/README.md#L129)只明确列出 `Belle-whisper-large-v3-zh`，推理引擎为 Transformers，镜像版本为 v1.2，MR/BI150 和 BI100 均标记支持；[厂商样例](../../bi150/README.md#L633)也只给出了 Belle 的 ASR 入口。清单没有列出 Fun-ASR-Nano、`openai/whisper-large-v3`、Whisper medium/small 或 Qwen3-ASR。

共享盘现在包含 Fun-ASR-Nano、Belle、Whisper large-v3、Whisper medium 和 Qwen3-ASR-1.7B 权重；
FunASR 安装在项目独立环境中。权重存在不等于厂商兼容性声明，当前 Fun-ASR-Nano 的兼容性依据为本项目实测。

## 候选对比

| 模型 | 规模与语言 | 输入长度 | 时间戳 | 流式能力 | 许可证与官方框架 |
| --- | --- | --- | --- | --- | --- |
| `FunAudioLLM/Fun-ASR-Nano-2512` | 800M；中文、英语、日语，中文含吴语、粤语、闽语、客家话、赣语、湘语、晋语及 26 种地域口音；也支持歌词和说唱识别。 | 实时服务接收 16 kHz 单声道 PCM16；动态 VAD 负责连续会话分句。离线 vLLM 单次长音频可能截断，官方要求先用 VAD 分段。 | 原始 ModelScope 检查点包含 CTC 权重，可生成字符级时间戳；当前 Hugging Face 原始检查点缺少该部分权重，需时间戳时应固定 ModelScope 制品。实时协议稳定字段是 VAD 分句的 `start/end`，不能把它等同于每字时间戳。 | 官方 `serve_realtime_ws.py` 接收约 100 ms 音频帧，默认约每 480 ms 刷新可替换的 `partial`，VAD 句末输出锁定的 `sentences`。声学编码器本身是全上下文非因果模型，每次 partial 会重新编码当前句，所以属于实时增量服务能力，而非可缓存历史状态的原生因果流式模型。 | 模型权重 Apache-2.0；FunASR 工具包为 MIT。常规推理使用 FunASR/PyTorch，低延迟流式服务使用 FunASR split engine + vLLM。见[官方模型仓库](https://github.com/QwenAudio/Fun-ASR)、[模型卡](https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512)及[vLLM/流式服务指南](https://github.com/modelscope/FunASR/blob/main/docs/vllm_guide.md)。 |
| `BELLE-2/Belle-whisper-large-v3-zh` | Whisper large-v3 中文全量微调；底层 large 架构约 1.55B。官方只明确宣称中文增强，并在 AISHELL-1/2、WenetSpeech、HKUST 上给出 CER。 | 16 kHz；继承 Whisper 的 30 秒感受野，长文件需分窗。 | 模型卡未单独承诺。基于 Whisper 架构可尝试分段/词级时间戳，但应列为待实测功能。 | 官方未提供增量流式接口。 | 模型卡标记 Apache-2.0，示例使用 Transformers。见[模型卡](https://huggingface.co/BELLE-2/Belle-whisper-large-v3-zh)、[配置](https://huggingface.co/BELLE-2/Belle-whisper-large-v3-zh/blob/main/config.json)和[预处理配置](https://huggingface.co/BELLE-2/Belle-whisper-large-v3-zh/blob/main/preprocessor_config.json)。 |
| `openai/whisper-large-v3` | 1.55B，多语言；Hugging Face 的 OpenAI 模型页标记 99 languages，并加入粤语 token。 | 单窗口 30 秒；官方 `transcribe()` 对完整文件使用滑动 30 秒窗口，Transformers 也提供 sequential/chunked 长音频算法。 | 支持分段时间戳；Transformers 还提供词级时间戳。 | 官方模型卡明确说明不能开箱即用地做实时转写，业务层分块并不等同模型原生流式。 | OpenAI 原始代码仓库为 MIT；Hugging Face 检查点页面标记 Apache-2.0，制品来源的许可证元数据存在差异，落地前应固定来源。见[OpenAI README](https://github.com/openai/whisper/blob/main/README.md)、[OpenAI 模型卡](https://github.com/openai/whisper/blob/main/model-card.md)及[HF 模型页](https://huggingface.co/openai/whisper-large-v3)。 |
| `Qwen/Qwen3-ASR-1.7B` | 名称标称 1.7B；技术报告说明模型由 Qwen3-1.7B、300M AuT 音频编码器和 projector 组成。支持语言识别、30 种语言、22 种中文方言，以及语音、歌声和带 BGM 歌曲。 | 官方最大单次 ASR 输入 1200 秒，即 20 分钟；更长文件仍应在服务层分段。 | ASR 本体输出语言和文本；词/字级时间戳需额外使用 `Qwen3-ForcedAligner-0.6B`，后者单次最长 300 秒。 | 原生支持离线和流式；当前官方实现的流式仅支持 vLLM 后端，不支持批处理，也不能同时返回时间戳。 | Apache-2.0。官方 `qwen-asr 0.0.6` 要求 Python ≥3.9，锁定 Transformers 4.57.6、Accelerate 1.12.0，vLLM extra 锁定 vLLM 0.14.0。见[模型卡](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)、[技术报告](https://arxiv.org/html/2601.21337)、[官方仓库](https://github.com/QwenLM/Qwen3-ASR)及[依赖文件](https://github.com/QwenLM/Qwen3-ASR/blob/main/pyproject.toml)。 |

Belle 是 Whisper large-v3 的微调版本，参数量和 30 秒窗口取自其官方基座及公开配置；“可尝试 Whisper 时间戳”是架构推断，不是 Belle 模型卡或厂商样例已经验收的能力。[Belle 模型卡](https://huggingface.co/BELLE-2/Belle-whisper-large-v3-zh)明确显示其 base model 为 `openai/whisper-large-v3`；[Whisper large-v3 官方资料](https://huggingface.co/openai/whisper-large-v3)说明 30 秒感受野、长音频算法和时间戳用法。

## Fun-ASR-Nano 的实时流式适合度

Fun-ASR-Nano 的官方实时服务是真正按音频到达持续工作的增量接口：客户端以 WebSocket 发送 `START`、16 kHz PCM16 二进制帧及 `STOP`，服务端持续推送可覆盖更新的 `partial`，VAD 检测到句末后将文本锁定进 `sentences`，最后返回 `is_final=true`。它还支持 `LANGUAGE:`、`HOTWORDS:`，服务端可以选择开启说话人分配。[官方协议](https://github.com/modelscope/FunASR/blob/main/docs/vllm_guide.md#63-websocket-protocol)已经足以作为项目 `/asr/v1/realtime` 的上游协议基础。

这里的“实时”需要准确理解。官方文档说明其 SenseVoice 声学编码器是全上下文、非因果编码器，每次 partial 都从当前句开头重新编码到当前时刻；默认预览窗口为 8 秒，用于限制长句的重复计算。它能提供用户可见的实时字幕，但长时间无停顿的连续讲话会使预览计算量随句长增加，不能按典型 causal streaming encoder 的常量增量成本估算。[流式机制与长句限制](https://github.com/modelscope/FunASR/blob/main/docs/vllm_guide.md#65-partial-preview-mechanism-and-long-sentence-behavior)说明约 29 秒连续句子会被反复全量编码，生产验收必须覆盖长句和并发。

功能上，它比 Qwen3-ASR 当前开源 SDK 更接近本项目需求：

- **热词**：Fun-ASR-Nano WebSocket 原生接受 `HOTWORDS:`，适合人名、产品名和行业词；Qwen3-ASR 提供自由文本 `context`，但不是相同的显式热词接口。
- **VAD 和句子状态**：Fun-ASR-Nano 服务内含独立 FSMN-VAD，区分可覆盖的 `partial` 和不可变的 `sentences`；Qwen3-ASR 官方最小流式演示把整条音频当作一个 session，约每 2 秒累计重解码，没有配套的生产 WebSocket/VAD 分句协议。
- **时间信息**：Fun-ASR-Nano 的 ModelScope 原始检查点具有 CTC 字符对齐能力；实时 WebSocket 至少返回 VAD 句段起止时间。Qwen3-ASR 流式模式明确不支持时间戳，离线时间戳需要另载 0.6B ForcedAligner。
- **并发**：FunASR 当前服务实现包含按连接隔离的 VAD、线程工作单元和最多 16 段的合批入口，但官方同时要求实际压测长会话与多客户端。Qwen3-ASR 官方流式 API 明确不支持 batch，其示例也不是生产并发契约。两者都不能在 BI150 上跳过并发验收。

公开结果不能证明 Fun-ASR-Nano 一定比 Qwen3-ASR-1.7B 更准。Fun-ASR-Nano 发布方的表格没有纳入 Qwen3-ASR；Qwen3-ASR 发布方的多语言表格主要比较的是另一个 `Fun-ASR-MLT-Nano` 检查点。两者训练数据、语言集合、VAD 和评测规范也不同。选择顺序应先按产品功能和本机兼容性确定，再用同一批真实音频比较 CER/WER、首个 partial 延迟和句末延迟。

官方还提供 `POST /v1/audio/transcriptions` 兼容接口，但这是整文件转写接口；本项目不部署该路径。
实时字幕走 WebSocket，NGINX 对实时路由保留 Upgrade、拉长读超时并关闭响应缓冲。

### 本机兼容性风险

本机 CoreX 定制 vLLM 0.17.0 的源码已注册 `FunASRForConditionalGeneration`，也具有 FunASR processor 和 `EmbedsPrompt` 支持；当前 split-engine 实测已经通过。不过 Fun-ASR-Nano 有两个不同的 vLLM 路径，不能混用：

1. 实时 `serve_realtime_ws.py` 使用原始 `FunAudioLLM/Fun-ASR-Nano-2512` 检查点和 FunASR split engine；它把 SenseVoice 编码器/适配器放在 PyTorch，将 Qwen3-0.6B 解码交给 vLLM。
2. `FunAudioLLM/Fun-ASR-Nano-2512-vllm` 是 vLLM 原生布局，官方目前验证的是 `POST /v1/audio/transcriptions` 文件转写；其模型卡明确要求流式、时间戳和说话人能力回到 FunASR 工具包与原始检查点。

官方 split-engine 安装基线使用 Python 3.12、vLLM 0.19.1 和 NVIDIA CUDA；原生 vLLM 制品的发布方验证边界则是 vLLM 0.27.1、PyTorch 2.13+cu129、Transformers 5.15 和 H100 80GB。[FunASR 安装基线](https://github.com/modelscope/FunASR/blob/main/docs/vllm_guide.md#1-installation--environment)和[原生 vLLM 制品验证边界](https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512-vllm#validation-boundary)都没有覆盖 Iluvatar BI-V150/CoreX。因此，当前本机实测是兼容依据，但尚不能外推到高并发、所有口音或长句精度。

资源方面，官方指南给出的通用起点是 GPU 至少 8 GB、推荐 16 GB；原始权重约 1.99 GB。它不是 BI150 实测显存。若 POC 采用 vLLM，`gpu_memory_utilization` 会预留大块设备显存，必须显式限制并测量与 YOLO、BGE-M3 共存时的峰值；不应照搬官方 H100 的参数。

## 资源备选

显存或并发压力使 large 级模型不合适时，可再验证多语言 `openai/whisper-medium`。官方规格为 769M，参考显存约 5 GB，参考速度约为 large 的 2 倍；本机共享盘已有该权重。`openai/whisper-small` 为 244M，参考显存约 2 GB、参考速度约为 large 的 4 倍，但本机共享盘未发现权重。这些显存与速度数据来自 OpenAI 在其环境中的近似值，不能直接当作 BI150 实测结果。[OpenAI 模型规格](https://github.com/openai/whisper/blob/main/README.md#available-models-and-languages)

medium 和 small 仍采用 Whisper 30 秒窗口，支持 Whisper 时间戳，但没有官方原生增量流式能力；模型缩小也会带来识别质量风险。对本机而言 GPU 0 目前并不缺少装载 large 级模型的静态显存，只有实际并发或后续 TTS 资源竞争出现后，才有必要优先牺牲 ASR 模型规模。

## 框架兼容性判断

- Belle 的本地权重配置记录 `torch_dtype=float32`，单个 safetensors 文件约 6.17 GB；厂商 `infer.py` 样例没有显式改精度。首轮兼容性验证应先复现厂商路径，再单独验证 FP16 是否准确、稳定并确实节省显存，不能把 NVIDIA 上的优化结论直接套到 BI150。
- Qwen3-ASR 官方包所需 Transformers 4.57.6 与本机版本一致；本机定制 vLLM 也已包含 `Qwen3ASRForConditionalGeneration` 和 `Qwen3ASRRealtimeGeneration` 注册代码。这是值得试验的积极信号。官方 `qwen-asr[vllm]` 依赖却锁定上游 vLLM 0.14.0，而本机是 CoreX 定制 vLLM 0.17.0；不能直接执行依赖升级或替换，否则可能破坏现有 VLM/RAG 环境。
- FunASR 工具包本身声明 Python ≥3.8，本机 Python 3.10 满足基础版本条件；官方实时 vLLM 指南以 Python 3.12 和 vLLM 0.19.1 为起点。本项目已经固定 FunASR commit 与模型权重，并在独立环境中只复用 CoreX torch/vLLM，没有安装通用 vLLM wheel。
- Whisper large-v3、medium 和 small 虽可由当前 Transformers 架构加载，厂商清单并未承诺这些具体检查点。Belle 的适配结果也不能自动扩展成所有 Whisper 检查点均受厂商支持。

## 落地条件

选择 Belle 时，首版接口可沿用已预留的 `POST /asr/v1/audio/transcriptions`，先提供完整文件上传、文本结果和可选语言固定为中文；长音频在服务端切分。时间戳与近实时分块输出需在本机实测后再写入契约。

选择 Qwen3-ASR 时，应先在独立环境验证离线 Transformers 路径，再验证 CoreX vLLM 的 OpenAI transcription API 和 realtime 路径；不得替换现有共享环境中的 CoreX torch/vLLM。若需要时间戳，还要把 0.6B ForcedAligner 的显存、延迟和 300 秒分段纳入整体预算；若需要流式，接口应另行定义 WebSocket 或等价的双向音频会话契约，不能只复用文件上传接口。

Fun-ASR-Nano 的固定源码、ModelScope 原始检查点、单条直接识别、split-engine vLLM 和统一网关 WebSocket 已经完成。下一轮验收至少包含：partial 刷新间隔、句末 final 延迟、10/30/60 秒无停顿长句、1/4 路并发、热词命中率、断线清理、峰值显存和与 YOLO/RAG 共存的尾延迟。

无论选择哪一个，进入部署前都需要用真实中文业务音频验收：安静与噪声、远场、专业词、数字、中英混说、长静音和长音频；同时测量 GPU 0 上 ASR 与 YOLO/RAG 共存时的峰值显存、首个转写结果延迟、整段处理耗时和失败恢复。模型发布方的 benchmark 不能替代这些本机业务测试。
