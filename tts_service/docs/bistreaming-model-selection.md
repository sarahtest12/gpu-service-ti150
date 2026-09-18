# 双流 TTS 模型选型

调研日期：2026-09-17。本文只讨论可本地部署的真正 bi-streaming：模型在同一次生成中持续消费新增文本，同时持续输出可播放音频。仅把完整文本切成多次独立请求，或只对完整文本做音频分块，不算严格意义上的模型级双流。

## 结论

本项目首选 **`FunAudioLLM/Fun-CosyVoice3-0.5B-2512`，使用标准 `llm.pt` 和 CosyVoice 原生 PyTorch 推理路径**。它的官方实现已经提供文本 `Generator` 输入、`inference_bistream()` 增量解码和音频 chunk 输出，模型规模为 0.5B；相比 CosyVoice2，官方评测中的中文内容正确率和说话人相似度更好。当前服务已经在 BI-V150/CoreX 上跑通 CosyVoice 1，因此迁移同一代码系的 CosyVoice3，比移植整套上游 vLLM-Omni 更可控。

不要为双流启用 CosyVoice 的 vLLM 后端。官方代码明确限制：文本为 `Generator` 时只允许 CosyVoice2/3，且不能存在 `llm.vllm`；双流应使用原生 PyTorch LLM、`stream=True` 的 token-to-wave 流式解码，再由本项目实现 WebSocket 会话和线程安全的文本队列。[CosyVoice 模型入口](https://github.com/QwenAudio/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/cli/model.py#L100-L113) [双流 LLM 实现](https://github.com/QwenAudio/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/llm/llm.py#L552-L662)

`Qwen3-TTS` 适合作为第二条技术路线。如果运行环境以后换成标准 CUDA，或天数正式提供兼容的 vLLM-Omni，它的 CustomVoice 模型有固定预置音色，官方 vLLM-Omni 也已提供 WebSocket 增量文本输入和 PCM 音频输出。当前 BI-V150 上不建议把它作为首选，因为本机是 Python 3.10、CoreX Torch 2.7.1 和 ixFormer，而上游 vLLM-Omni 当前要求 Python 3.12、与其同版本的上游 vLLM；两套运行时不能视为等价。[vLLM-Omni 安装要求](https://docs.vllm.ai/projects/vllm-omni/en/latest/getting_started/quickstart/#installation)

## 候选比较

| 候选 | 严格模型级文本流入 | 音频流出 | 音色方式 | 模型规模 | 对本机判断 |
| --- | --- | --- | --- | --- | --- |
| Fun-CosyVoice3-0.5B-2512 标准版 | 是，原生 `Generator` + `inference_bistream()` | 是，`stream=True` 持续 yield PCM tensor | 零样本参考音频；需由服务端建立固定音色档案 | 0.5B | **首选，先做兼容性 POC** |
| Fun-CosyVoice3-0.5B-2512 RL 权重 | 同标准版 | 同标准版 | 同标准版 | 0.5B | 暂不选；内容指标更好，但官方 SS 略低 |
| CosyVoice2-0.5B | 是，与 CosyVoice3 共用双流入口 | 是 | 零样本参考音频；可缓存说话人档案 | 0.5B | CV3 失败时的回退方案 |
| Qwen3-TTS-12Hz-0.6B-CustomVoice | 架构支持；官方 `qwen-tts` Python API 尚不提供严格双流，vLLM-Omni 提供增量 WebSocket 服务 | vLLM-Omni 支持 PCM chunk | 9 个预置音色，其中 5 个中文/方言音色 | 0.6B | 音色接口合适，但 CoreX/vLLM-Omni 未验证 |
| Qwen3-TTS-12Hz-1.7B-CustomVoice | 同上 | 同上 | 同样 9 个预置音色，并支持 instruction 控制 | 1.7B | 标准 CUDA 环境的高质量备选；移植风险更高 |

### Fun-CosyVoice3-0.5B-2512

官方将 CosyVoice3 的 bi-streaming 定义为同时支持 text-in streaming 和 audio-out streaming，并给出最低 150 ms 的官方延迟表述。官方代码对输入生成器逐批取文本 token，并在文本仍可能继续到达时生成语音 token；外层 `tts(..., stream=True)` 在 token 达到窗口后持续输出音频块。这满足严格的模型级双流定义。[官方 README：Bi-Streaming](https://github.com/QwenAudio/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/README.md#key-features) [官方示例：文本生成器](https://github.com/QwenAudio/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/example.py#L60-L68) [音频分块实现](https://github.com/QwenAudio/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/cli/model.py#L188-L234)

官方示例中的双流片段把 `stream` 留为 `False`，该示例只展示生成器输入。项目实现严格双流时必须同时传 `Generator` 和 `stream=True`；这点应通过真实首包延迟测试验证，不能直接套用 README 中的 150 ms 数字。

CosyVoice3-2512 官方评测为：中文 CER 1.21%、中文说话人相似度 SS 78.0%；CosyVoice2 分别为 1.45% 和 75.7%。英文和 hard 集上，CosyVoice3 标准版的 SS 也高于 CosyVoice2。对当前“音色一直变化”的问题，这些指标支持优先选 CosyVoice3，但它们是数据集级指标，不是对同一会话每段音频声纹一致性的保证。[官方评测表](https://github.com/QwenAudio/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/README.md#evaluation) [CosyVoice3 论文](https://arxiv.org/abs/2505.17589)

2512 模型仓库同时包含 `llm.pt` 和 `llm.rl.pt`。官方 `AutoModel` 默认加载 `llm.pt`，因此这里所说的标准版是同一模型仓库中的标准 LLM 权重，并非另一个模型 ID。[默认权重加载](https://github.com/QwenAudio/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/cli/cosyvoice.py#L189-L222) [官方 Hugging Face 模型仓库](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512)

首版不选 `llm.rl.pt`。官方结果显示 RL 版把中文 CER 从 1.21% 降到 0.81%，但中文 SS 从 78.0% 降到 77.4%，英文 SS 从 71.8% 降到 69.5%，hard 集 SS 从 75.8% 降到 75.0%。当前优先目标是固定音色，标准版更符合目标。RL 可在标准版稳定后作为独立 A/B 候选，不能只因 CER 更低直接替换。

模型仓库的完整快照约 9.75 GB，其中包含标准与 RL 两套约 2.02 GB 的 LLM 权重、PyTorch/ONNX 的 flow 和两份 speech tokenizer ONNX 文件；下载体积不等于运行显存。BI-V150 的 32 GB 容量对单个 0.5B TTS 模型通常不是首要障碍，但本项目还同时驻留 VLM、ASR 等模型，因此必须实测启动峰值、稳定显存和并发生成峰值，不能仅凭参数量承诺可与所有服务同时常驻。[模型文件列表](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512/tree/main)

CosyVoice3 没有当前 CosyVoice-300M-Instruct 那组可直接沿用的“中文女、中文男”等 SFT 预置 ID。它是零样本音色路线，项目应为每个公开 `voice` 配置一份服务端持有的参考音频和准确文本，启动时提取并缓存 prompt 信息，会话内固定使用同一份 prompt。不要假设当前 300M 模型的 `spk2info.pt` 能跨模型直接复用；CosyVoice3 使用不同 speech tokenizer 和模型配置。[CosyVoice3 零样本示例](https://github.com/QwenAudio/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/example.py#L71-L91)

### CosyVoice2-0.5B

CosyVoice2 是可靠的回退候选。论文和官方仓库都把它定位为可扩展的流式 TTS，当前源码中的 `inference_bistream()` 同时处理 CosyVoice2 的 `Qwen2LM` 和 CosyVoice3 的 `CosyVoice3LM`。[CosyVoice2 论文](https://arxiv.org/abs/2412.10117) [双流类型分支](https://github.com/QwenAudio/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/llm/llm.py#L565-L575)

它的完整官方模型快照约 4.86 GB，明显小于同时携带标准/RL 权重的 CosyVoice3-2512 快照；参数规模仍为 0.5B。[官方模型仓库](https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B) 代价是官方 SS、中文 CER 和多语种覆盖都弱于 CosyVoice3，且 CosyVoice3 对 text normalization、方言和复杂文本的能力更完整。因此只有在 CosyVoice3 的 CoreX 算子、显存或实时性验证失败时，才建议退回 CosyVoice2。

### Qwen3-TTS 开源系列

Qwen3-TTS 的 12Hz 模型架构本身为流式设计。官方技术报告描述 dual-track LM、12.5 Hz 多码本 tokenizer 和因果 ConvNet，并报告最低 97 ms 首包延迟；0.6B/1.7B Base、CustomVoice 以及 1.7B VoiceDesign 都在官方模型表中标为 Streaming。[Qwen3-TTS 技术报告](https://arxiv.org/abs/2601.15621) [官方模型表](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/README.md#released-models-description-and-download)

不过，模型能力、`qwen-tts` Python 包和服务框架要分开判断：

- 官方 `qwen-tts` 包的 `generate_custom_voice()`、`generate_voice_clone()` 等接口接收完整字符串，先生成完整 codec，再整体 decode 并返回 waveform。其 `non_streaming_mode=False` 文档明确写的是模拟流式文本布局，不会开启真正的流式输入或流式生成。[官方 Python 实现](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/qwen_tts/inference/qwen3_tts_model.py#L470-L633)
- 截至本次调研，上游 vLLM-Omni 已提供 `/v1/audio/speech/stream` WebSocket：客户端可连续发 `input.text`，服务端返回 PCM 二进制帧。默认 `split_granularity=none` 时会缓冲到 `input.done`，以一次 TTS 请求合成来保持长文本音色稳定；设为 `sentence` 或 `clause` 才会在边界处提前启动，但每个边界对应一次新的 TTS 请求。因此它满足“协议层持续追加文本 + 音频流出”，但 sentence/clause 模式不等同于一个模型 decode 持续消费任意字符。[vLLM-Omni Speech API](https://github.com/vllm-project/vllm-omni/blob/main/docs/serving/speech_api.md#streaming-text-input-websocket) [Qwen3-TTS WebSocket 示例](https://docs.vllm.ai/projects/vllm-omni/en/latest/user_guide/examples/online_serving/qwen3_tts/#streaming-text-input-websocket)

如果以后能使用 vLLM-Omni，面向固定中文预置音色优先考察 `Qwen3-TTS-12Hz-0.6B-CustomVoice`。它提供 Vivian、Serena、Uncle_Fu、Dylan、Eric 等中文或中文方言预置音色，规模较小；但官方模型表没有为 0.6B CustomVoice 标注 instruction control。[官方音色列表](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice#supported-speakers)

若必须保留情绪/风格 instruction，则考察 `Qwen3-TTS-12Hz-1.7B-CustomVoice`。官方对 1.7B CustomVoice 标注了 instruction control，同样提供 9 个固定预置音色。[官方 README](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/README.md#released-models-description-and-download) 1.7B 在 32 GB 卡上从参数量看有部署空间，但本项目多服务共卡，且 CoreX 尚未验证其算子、注意力实现和 vLLM-Omni 多阶段执行，因此不能据此承诺能运行。

## BI-V150 / CoreX 风险

本机实测环境是 BI-V150 32 GB、Python 3.10、`torch 2.7.1+corex.4.4.0`；当前 TTS 服务还固定了一组与上游不同的依赖。官方 CosyVoice `requirements.txt` 固定 `torch==2.3.1`、`torchaudio==2.3.1`、`transformers==4.51.3`，并以 CUDA、TensorRT 和 NVIDIA Triton 为主要加速路径。[CosyVoice 官方依赖](https://github.com/QwenAudio/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/requirements.txt) 当前环境见项目的 [TTS 启动检查](../scripts/service.py) 和 [BI150 镜像说明](../../bi150/README.md)。

CosyVoice3 的官方前端在 `torch.cuda.is_available()` 为真时强制为 speech tokenizer 选择 ONNX Runtime `CUDAExecutionProvider`；本项目安装的 ONNX Runtime 只有 CPU provider，而 CoreX 对 PyTorch 暴露为 CUDA 兼容接口。这会导致未经修改的上游前端选中不存在的 provider，是迁移 POC 必须先处理和验证的明确问题。[官方 provider 选择代码](https://github.com/QwenAudio/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/cosyvoice/cli/frontend.py#L40-L48)

CosyVoice 官方的 TensorRT-LLM/Triton 部署依赖 NVIDIA 容器、TensorRT engine 和 `--gpus all`，不能直接用于 BI-V150。首版应关闭 `load_trt` 和 `load_vllm`，只验证 CoreX PyTorch FP16/BF16 路径；speech tokenizer 可在 CPU ONNX provider 运行，但需测量它是否拖慢首音频延迟。[官方 CosyVoice3 TensorRT-LLM 部署](https://github.com/QwenAudio/CosyVoice/blob/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/runtime/triton_trtllm/README.Cosyvoice3.md)

Qwen3-TTS 的上游 vLLM-Omni 当前要求 Python 3.12、上游 vLLM 0.29.0 且两者主次版本一致；本机 BI150 镜像列出的 ixFormer/vLLM 是 0.11.2 或 0.17.0，并没有声明支持 vLLM-Omni 或 Qwen3-TTS 的多阶段 Code2Wav pipeline。因此不能把“ixFormer 能跑 Qwen3 文本模型”推导为“能跑 Qwen3-TTS WebSocket”。[vLLM-Omni Quickstart](https://docs.vllm.ai/projects/vllm-omni/en/latest/getting_started/quickstart/) [本地 BI150 支持矩阵](../../bi150/README.md)

## 建议验证顺序

1. 下载 `Fun-CosyVoice3-0.5B-2512`，明确加载标准 `llm.pt`，关闭 vLLM、TensorRT 和 JIT。
2. 在独立环境中修正 speech tokenizer provider 选择，先验证完整文本的零样本合成。
3. 用真实 Python generator 每 50～100 ms 追加一小段中文，同时设 `stream=True`，确认第一段文本未结束时已经收到第一块 PCM。
4. 为一个中文女声建立固定参考音频/文本档案，在同一个模型调用中连续追加 10～20 段文本；测首音频延迟、RTF、峰值显存、断句自然度和 CAM++ 声纹相似度。
5. 再与 CosyVoice2-0.5B 做同条件回退对比。只有 CosyVoice3 无法在 CoreX 稳定运行时才切换。
6. Qwen3-TTS 单独作为环境验证项目：先验证 0.6B CustomVoice 的纯 PyTorch完整请求，再评估是否值得为 CoreX 移植 vLLM-Omni；不要直接改造生产 TTS 服务。

该顺序把“模型确实支持双流”和“本机可以稳定运行双流”分成两项验证。当前官方资料可以确认前者，不能替代 BI-V150 上的实际兼容性和延迟测试。
