# RAG 候选模型：官方资料核实

后续选择与部署：用户已确定首版使用 BGE-M3、暂不部署 reranker，部署与验证见
[`rag_service/docs/validation.md`](../../rag_service/docs/validation.md)。下面保留选型阶段的研究快照。

核实日期：2026-09-10。依据模型发布方的一手资料、仓库内厂商资料及本机只读检查。本次未下载权重、运行 RAG 模型、改动依赖或服务；本文不构成 RAG 模型在 BI150/BI-V150 上的兼容性、显存或性能实测结论。

## 本机审查证据

本节合并同次任务的只读本机检查结果。`ixsmi` 快照时间为 2026-09-10 17:27（UTC+08:00），显存随运行负载变化：

| 设备 | 总显存 | 已用 / 空闲 | 已运行的模型进程 |
| --- | --- | --- | --- |
| GPU 0，Iluvatar BI-V150 | 32768 MiB | 272 / 32496 MiB | YOLO：192 MiB |
| GPU 1，Iluvatar BI-V150 | 32768 MiB | 27052 / 5716 MiB | VLM Engine：26968 MiB |

实际 Python 为 3.10.18，torch 为 `2.7.1+corex.4.4.0`，vLLM 为 `0.17.0+corex.4.5.0.rc.11.20260701`，ixformer 为 `0.7.0+corex.4.5.0.rc.11.20260701`，Transformers 为 4.57.6，Sentence Transformers 为 5.3.0。`bi150` 中 V4.3 PDF 是 2025 年资料，不能直接替代上述实际安装状态。

仓库[厂商模型列表](../../bi150/README.md#L112)列出 BGE 备选；[Qwen embedding](../../bi150/README.md#L117)和[Qwen reranker](../../bi150/README.md#L121)均在 MR/BI150 一栏标记支持 vLLM。[Embedding/Reranker 样例](../../bi150/README.md#L585)提供推理入口参考。因此 Qwen 0.6B 组合有本地厂商支持清单依据，但本次尚未执行 RAG 模型推理。

共享盘 `/share/fshare/common/models/Qwen/` 已存在两个 Qwen 0.6B 模型；检查到的 safetensors 文件分别为 1191586416 与 1191588280 bytes，配置为 BF16。合计约 2.38 GB 是磁盘权重文件大小，不能当作服务实际显存。

部署建议：首先在 GPU 0 与 YOLO 共存验证，从 BF16、短输入、低并发开始，测量显存峰值和对 YOLO 延迟的影响，再定批量及队列；继续为 ASR/TTS 留出空间。GPU 1 已主要供 VLM 使用。CPU 服务器负责分块、向量库、权限和 RAG 编排，生成回答可先复用既有 Qwen3.5-9B VLM。这些是本项目的部署建议，尚未实施。

Qwen reranker 的 vLLM 路径有专门配置：v0.17.0 官方示例使用 pooling runner、`hf_overrides` 将架构适配为 sequence classification，并提供 reranker 模板。不能直接套用普通 chat 服务启动方式。本次还在本机 vLLM 的 `models/config.py` 和 `models/adapters.py` 发现相应分类器支持代码，但是否完整兼容仍待实际加载验证。[vLLM v0.17.0 官方原始模型示例](https://raw.githubusercontent.com/vllm-project/vllm/v0.17.0/examples/pooling/score/qwen3_reranker_online.py)

## 模型规格

| 模型 | 用途 | 参数量 | 输出 | 官方长度 | 语言与适用特点 |
| --- | --- | --- | --- | --- | --- |
| `Qwen/Qwen3-Embedding-0.6B` | 向量召回 | 0.6B | 默认 1024 维，可选 32–1024 维 | 32K tokens | 100+ 语言，支持查询指令；中文、跨语言、代码检索候选。见[模型卡](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)。 |
| `Qwen/Qwen3-Reranker-0.6B` | 候选文本重排 | 0.6B | 每个 query/document 对的相关性分数 | 模型卡标称 32K tokens | 100+ 语言，支持任务指令。见[模型卡](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)。 |
| `BAAI/bge-large-zh-v1.5` | 向量召回 | 326M | 1024 维 | 512 tokens | 中文 BERT 编码器；适合已分块的中文资料。参数和语言见[BGE 官方文档](https://bge-model.com/tutorial/1_Embedding/1.2.1.html)，维度和长度见[配置](https://huggingface.co/BAAI/bge-large-zh-v1.5/blob/main/config.json)。 |
| `BAAI/bge-reranker-v2-m3` | 候选文本重排 | 568M | 每个 query/document 对的相关性分数 | tokenizer 配置 8192 tokens | 多语言 XLM-RoBERTa cross-encoder。参数和架构见[BGE 官方文档](https://bge-model.com/tutorial/5_Reranking/5.2.html)，长度见[tokenizer 配置](https://huggingface.co/BAAI/bge-reranker-v2-m3/blob/main/tokenizer_config.json)。 |
| `BAAI/bge-m3` | 向量召回；可扩展稀疏与多向量召回 | 568M | dense 1024 维；另有 sparse/ColBERT 输出 | 8192 tokens | 100+ 语言；无需给查询添加指令。见[模型卡](https://huggingface.co/BAAI/bge-m3)及[参数规格](https://bge-model.com/tutorial/1_Embedding/1.2.1.html)。 |

这些长度包含输入中的指令、特殊 token；reranker 还包含 query 和 document。长度单位不是汉字数，模型上限也不是服务应直接开放的默认上限。Qwen reranker 的配置记录 `max_position_embeddings=40960`，但选型仍按模型卡明确的 32K 能力描述，不能据配置擅自扩大服务承诺。[Qwen reranker 配置](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B/blob/main/config.json)

## 推理精度与调用方式

- **Qwen 组合**：两个模型的官方配置均记录 `torch_dtype=bfloat16`；模型卡也提供 FP16 推理示例。因此 BF16 或 FP16 均有官方使用依据，但具体国产卡算子和框架组合仍须实测。[Embedding 配置](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B/blob/main/config.json)、[Reranker 配置](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B/blob/main/config.json)、[官方仓库](https://github.com/QwenLM/Qwen3-Embedding)
- **BGE 组合**：官方 FlagEmbedding 示例均使用 `use_fp16=True`。`bge-large-zh-v1.5` 与 `bge-reranker-v2-m3` 的配置记录 FP32；这与允许加载后使用 FP16 并不矛盾。所查示例没有为这两个模型单独给出 BF16 保证，不能把其他 BGE LLM reranker 的 BF16 示例套用过来。[Embedding 模型卡](https://huggingface.co/BAAI/bge-large-zh-v1.5)、[Reranker 模型卡](https://huggingface.co/BAAI/bge-reranker-v2-m3)、[Embedding 配置](https://huggingface.co/BAAI/bge-large-zh-v1.5/blob/main/config.json)、[Reranker 配置](https://huggingface.co/BAAI/bge-reranker-v2-m3/blob/main/config.json)
- Qwen 官方示例要求 Transformers `>=4.51.0`，Embedding 的 Sentence Transformers 示例要求 `>=2.7.0`；示例还有 vLLM 路径。不能由上游最低版本号推导出本机厂商构建一定兼容，也不应为选型直接升级现有 VLM 环境。[官方仓库](https://github.com/QwenLM/Qwen3-Embedding)、[Embedding 使用说明](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- Qwen 官方建议查询侧配置任务指令，多语言场景优先用英语写指令；文档侧不加同样的检索指令。Embedding 使用最后一个有效 token 的隐层输出并作 L2 归一化，不能直接套 BERT 的 CLS pooling。官方 FlashAttention 2 加速建议不是 BI150 兼容证明。[官方仓库](https://github.com/QwenLM/Qwen3-Embedding)
- BGE 中文 v1.5 对短查询检索长文本建议使用检索指令，文档无需添加。官方支持 FlagEmbedding、Sentence Transformers 和普通 Transformers。模型卡提醒限制可见 GPU；本项目部署时应明确指定设备。[BGE 中文模型卡](https://huggingface.co/BAAI/bge-large-zh-v1.5)

## Reranker 分数语义

`Qwen3-Reranker-0.6B` 官方 Transformers 示例读取 `yes` 与 `no` 的 logits，再对两者归一化，输出 0–1 的相关性分数。当前 Sentence Transformers 示例默认输出两者的原始 logit 差，显式使用 Sigmoid 才映射到 0–1。不能只凭模型名假定返回值范围。[Qwen reranker 官方模型卡](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)

`bge-reranker-v2-m3` 默认返回原始 logit，可为负数；`normalize=True` 对它使用 Sigmoid，得到 0–1 分数。越高表示越相关。其模型卡中的 `max_length=512` 是示例截断长度，不是 tokenizer 标注的 8192 上限。[BGE reranker 官方模型卡](https://huggingface.co/BAAI/bge-reranker-v2-m3)、[tokenizer 配置](https://huggingface.co/BAAI/bge-reranker-v2-m3/blob/main/tokenizer_config.json)

接口设计建议：公开固定的 `relevance_score` 语义与模型 ID；若统一为 0–1，明确转换方法。不同模型的相同分数不应解释为同等准确率；业务过滤阈值应通过本项目标注样本确定。这是基于输出定义的工程建议，不是校准概率保证。

## 对本项目的候选排序

以下是有条件的选型判断，须与本机 `bi150` 资料、实际可用框架、并发预算合并判断。

1. **需要中文及中英混合、代码或较长文本，可优先验证 Qwen3 0.6B + 0.6B。** 两个组件同系列，向量维度可调，避免第一阶段直接引入 4B/8B 检索模型。官方支持范围不能替代本项目数据集上的检索质量测试。[Qwen 系列规格](https://github.com/QwenLM/Qwen3-Embedding)
2. **短中文知识片段、希望从经典编码器路径开始，可选 BGE-large-zh-v1.5 + BGE-reranker-v2-m3。** “保守”指 BERT/XLM-R 编码器调用路径及较小 embedding 参数量，不代表本机已经验证，亦不代表它必然比 Qwen 延迟低。512-token 召回输入上限须写进切块和接口规则。[BGE 系列](https://bge-model.com/tutorial/1_Embedding/1.2.1.html)、[BGE reranker](https://bge-model.com/tutorial/5_Reranking/5.2.html)
3. **需要长文本、多语言且希望保持 BGE 路径，可将 embedding 换成 BGE-M3。** 第一阶段可以仅输出 dense；只有业务确实需要时再开放 sparse/ColBERT，避免无意扩大 API 与索引方案。官方建议 RAG 使用混合召回加重排，但具体组合要由检索评测决定。[BGE-M3 官方模型卡](https://huggingface.co/BAAI/bge-m3)

所有候选仍需小批量验证：本机 GPU 成功执行且输出有限值；中文正负样本排序；相同模型的离线入库与在线查询预处理一致；与 YOLO/VLM 并存时的峰值显存和延迟。本文不提供未经实测的显存区间或耗时排名。
