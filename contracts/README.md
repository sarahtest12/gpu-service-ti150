# 算法服务契约 Review

初始 VLM/YOLO 契约基线为 `88bb84a`（add gateway）。随后已部署 BGE-M3，并增加 RAG 的三个公开接口。
监控部分继续保留已确认的设计，尚未实现；重排序模型暂不部署。

优先 review [`openapi.yaml`](openapi.yaml)。它是可导入 OpenAPI 工具的 **3.1.1** 单文件，
包含已有 HTTP 接口和待实现的监控接口，全部 schema 引用均在文件内部。
`x-implementation-status` 和操作摘要区分实现状态；实现状态不等于进程当前运行状态。
YOLO 的原生双向流使用 [现有 detector.proto](../yolov5v70-service/shared/detector_contract/detector.proto)，
输入、输出、限制与错误语义另见 [`yolo-grpc.md`](yolo-grpc.md)。

## 对外接口清单

| 协议 / 方法 | 路径 | 用途 | 契约状态 |
| --- | --- | --- | --- |
| HTTP GET | `/health/live` | 网关存活 | 已实现 |
| HTTP GET | `/vlm/health/ready` | VLM 引擎就绪 | 已实现 |
| HTTP GET | `/yolo/health/ready` | YOLO 就绪 | 已实现 |
| HTTP GET | `/vlm/v1/models` | VLM 模型列表 | 已实现 |
| HTTP POST | `/vlm/v1/chat/completions` | 文本、图片、工具、完整 JSON / SSE | 已实现 |
| gRPC 双向流 | `/detector.v1.Detector/Detect` | YOLO 视频帧检测 | 已实现，`.proto` 为唯一契约源 |
| HTTP GET | `/monitor/v1/overview` | 服务状态、显存、最近 60 秒耗时 | 已对齐的设计，未实现；当前 404 |
| HTTP GET | `/rag/health/ready` | BGE-M3 引擎就绪 | 已实现 |
| HTTP GET | `/rag/v1/models` | 向量模型列表 | 已实现 |
| HTTP POST | `/rag/v1/embeddings` | BGE-M3 文本向量编码 | 已实现 |
| HTTP POST | `/rag/v1/rerank` | 检索重排 | 预留路径，当前 404 |
| HTTP POST | `/asr/v1/audio/transcriptions` | 语音识别 | 预留路径，当前 404 |
| HTTP POST | `/tts/v1/audio/speech` | 语音合成 | 预留路径，当前 404 |

RAG rerank、ASR、TTS 记录在 OpenAPI 的 `x-reserved-interfaces`，没有加入可调用的 `paths`。
YOLO 普通 HTTP 单图接口也尚未定义。监控的 RAG 耗时字段只是观测口径，不意味着已有 RAG 推理接口。

统一目标为 `https://GPU_HOST:8443`，gRPC 客户端 target 为 `GPU_HOST:8443`。
全部对外接口，包括健康检查，使用 `Authorization: Bearer <GPU_API_KEY>`。
调用方验证 TLS 证书；目标名称校验不限制调用方 IP 或域名。key 由 CPU 后端保存。

## 监控契约

仅保留已确认的三个指标组，不加入整卡显存、利用率、温度、请求量、排队数、错误率等指标。
采样时间与统计窗口是数据时效的元信息。无请求体或查询参数；每 5 秒采样，保留最近 60 秒统计。

| 字段 | 约定 |
| --- | --- |
| `sampled_at` | UTC 采样时间 |
| `window_seconds` | 固定 `60` |
| `services[].name` | 当前已定义口径的 `yolo`、`vlm`、`rag`；仅实际部署的服务出现 |
| `services[].status` | `running` / `error`，对应运行中 / 异常 |
| `services[].memory_mb` | 运行中服务的进程显存合计，含推理子进程；MB = 1000000 字节 |
| `services[].latency.metric` | YOLO `model_inference`；VLM `time_to_first_token`；RAG `http_request` |
| `services[].latency.avg_ms` | 最近 60 秒平均耗时，毫秒 |
| `services[].latency.p95_ms` | 最近 60 秒 P95 估算，毫秒 |

运行中服务必须带显存与耗时字段；采集不到的数值使用 `null`。没有耗时样本时均为 `null`。
异常服务只返回 `name`、`status`，不能携带上一次的显存或耗时。
未部署服务不生成记录，不返回 `not_deployed` 状态。同一服务名在数组中最多出现一次。
已部署但主动停止也按 `error` 展示。ASR、TTS 的专用耗时口径需要在后续接入前定义并扩展契约。

YOLO 口径为 GPU 主机端每帧模型推理耗时，排除预处理、排队、NMS 和网络；当前批量大小为 1。
VLM 为 GPU 端首 token 延迟，包含排队，排除 CPU 与 GPU 间网络。
RAG 为 HTTP 请求在 GPU 主机应用中的完整处理耗时，不等同于单个 GPU kernel 的执行时间。

HTTP 200 表示取得监控快照，其中可以存在 `error` 服务。
监控进程或上游连接不可用可能由 NGINX 返回 502/504；采样尚未就绪、失败或过期的应用响应设计为
503 JSON `{"error":"monitor_unavailable"}`。401 继续使用已有 NGINX 鉴权响应。

以下是实施前需要 review 的细节建议，尚未写入服务代码：

1. 快照超过 15 秒（3 个采样周期）视为过期，返回 503；已确认需要防止旧数据冒充实时值，具体阈值此前未指定。
2. 模型或监控重启后，从新采样基线重新建立统计，不把进程生命周期累计值当作最近 60 秒；不足窗口使用已有样本。
3. P95 落入无穷上界桶、或无法可靠估算时返回 `null`；平均值仍可单独返回。
4. 当前运行状态只有两个取值；启动中尚未通过健康检查时暂显示 `error`，不新增第三种状态。

## VLM 契约说明

`Vlm_*` schema 由本机 `vllm==0.17.0+corex.4.5.0.rc.11.20260701` 的五个 Pydantic 协议模型导出，
未加载权重。来源模块在 OpenAPI 的 `x-source.schema_models`。
不同根模型的同名子类型可能不同，所以按根模型命名空间展开，避免错误复用 `FunctionCall` 等定义。
字段完整性以这份锁定版本快照为准；Pydantic 自定义跨字段校验不一定能全部表达为 JSON Schema。

schema 包含上游支持的所有请求字段，但部署能力仍受项目配置限制：当前支持文本、最多两张图片和工具调用，
不承诺上游列出的音视频、其他模型或所有扩展参数均可用于此部署。优先 review 操作中的三种请求示例。
`model` 可选/可空、`tools` 参数等保留上游实际类型；CPU 示例通常显式指定 `qwen3.5-9b`。
项目客户端默认 `temperature=0`、`max_completion_tokens=512`、`enable_thinking=false`，这些不是网关强制默认值。

SSE 的 HTTP 响应体是 `text/event-stream`，在 OpenAPI 中定义为字符串。
单个 `data` 事件的 JSON schema 通过 `x-event-data-schema` 关联；`[DONE]` 单独作为结束标记。
这能 review 事件内容，但普通 OpenAPI 客户端生成器未必自动生成流式迭代代码。
工具参数需要按索引拼接后在 CPU 校验执行；`choices=[]` 的最终 usage 事件有效。
HTTP 200、`[DONE]` 或连接结束本身不能证明正常生成；需要结合 `finish_reason`，断流时保留未完成语义。

## RAG 契约说明

`Rag_EmbeddingCompletionRequest`、`Rag_EmbeddingResponse` 及子类型从同一个锁定版本 vLLM 导出。
模型列表和错误复用已有 vLLM 的 `ModelList` / `ErrorResponse` schema。
当前支持基于 `input` 的文本或 token ID 编码，推荐字符串/字符串数组和 `encoding_format=float`；
`base64` 输出也已经验收。上游 chat/messages 和二进制扩展不作为 CPU 示例的支持契约。

模型 `bge-m3` 默认返回 CLS pooling、L2 归一化后的 1024 维向量。
`use_activation=false` 会关闭归一化；`dimensions` 不是本模型的可变维度功能，应省略。
服务当前单段最多 2048 tokens，包含特殊 token，超长默认返回 400；模型原生 8192 上限不等于当前服务限制。
CPU 建议批次不超过 16 段，这是使用建议；服务实际硬限制为 256 KiB 请求体和引擎调度预算。
默认不截断输入，文档分块、入库、检索、权限由 CPU 项目负责。
详细部署限制与真实验证见 [`rag_service/README.md`](../rag_service/README.md) 和
[`rag_service/docs/validation.md`](../rag_service/docs/validation.md)。

## 当前实现需要留意的差异

- VLM/RAG 健康检查 200/503 为空响应体；YOLO 健康检查返回 JSON。
- NGINX 401、403、413、502、504 等通常返回 HTML；当前没有统一 JSON 错误包装。
- 当前 vLLM 请求字段校验错误转换为 400，不能默认写成 FastAPI 422 错误格式。
- `/health/live` 当前固定返回实现未限定 HTTP 方法；本契约只约定客户端使用 GET。
- 不支持的路径在正确鉴权后返回 404；无 key 时先得到 401。
- 网关保留上游错误；应用侧应对返回给前端的错误信息脱敏。
- 网关生成 `X-Request-ID`，并不保证它与 VLM 的 `chatcmpl-*` id 相同。
- OpenAPI 文件当前没有发布为网关 `/openapi.json`、`/docs` 路由；本轮交付是 review 文件。

## 内部接口范围

以下是项目使用和文档支持的本机诊断入口，不开放给 CPU 后端，不使用对外共享 key 直连。
它们在这里列出，避免将内部诊断接口误当作遗漏的公共接口。

| 内部地址 | 路径 | 形式 / 鉴权 |
| --- | --- | --- |
| `127.0.0.1:8000` | `/health` | VLM 健康检查，空响应体；当前上游无需 key |
| `127.0.0.1:8000` | `/metrics` | vLLM Prometheus 文本指标；当前上游无需 key |
| `127.0.0.1:8000` | `/v1/models`、`/v1/chat/completions` | VLM 内部 key，内容结构对应公共 VLM 契约 |
| `127.0.0.1:8081` | `/health/live`、`/health/ready` | YOLO JSON 健康检查；仅本机，无 key |
| `127.0.0.1:8081` | `/metrics` | YOLO Prometheus 文本指标；仅本机，无 key |
| `127.0.0.1:50051` | `/detector.v1.Detector/Detect` | 同一 protobuf 契约，使用 YOLO 内部 key |
| `127.0.0.1:8002` | `/health` | RAG 健康检查；空响应体，本机无需 key |
| `127.0.0.1:8002` | `/v1/models`、`/v1/embeddings` | RAG 内部 key，对应公共 RAG 契约 |
| `127.0.0.1:8002` | `/metrics` | vLLM 内部诊断指标；不转发到统一网关 |

厂商 vLLM 包中其他管理、tokenize 或文档路由没有被网关转发，不属于本项目对 CPU 的支持契约。

## Review 与校验

可在支持 OpenAPI 3.1 的 Swagger Editor、Swagger UI 或其他契约工具中导入 `openapi.yaml`。
也可以直接看 YAML 的 `paths`，再按 `$ref` 找到对应输入输出结构。
不要根据 `proposed` 操作生成“已上线”列表；预留接口的请求/响应需要另行设计。

初始契约与 RAG 增量校验结果记录在 [`validation.md`](validation.md)。

描述规范依据：[OpenAPI 3.1.1](https://spec.openapis.org/oas/v3.1.1.html)；
gRPC 双向流语义依据：[gRPC 核心概念](https://grpc.io/docs/what-is-grpc/core-concepts/)。
P95 的直方图估算说明见 [Prometheus 直方图文档](https://prometheus.io/docs/practices/histograms/)。
