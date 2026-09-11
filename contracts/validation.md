# 契约校验记录

## 初始契约校验

日期：2026-09-10。实现基线：`88bb84a`。该轮只创建契约文档，并为根 README 增加入口链接。
没有启动网关或算法、加载模型、修改服务代码或全局 SDK，也没有把监控接口部署上线。

| 校验 | 结果 |
| --- | --- |
| `openapi-spec-validator==0.7.2` 校验 OpenAPI 3.1.1 | 通过 |
| 86 个 schema 的 JSON Schema 结构 | 通过 |
| 全部 `$ref` 引用在同一文件内可解析 | 通过 |
| 13 个操作内请求/响应示例 | 通过 |
| SSE 示例中的 4 个 JSON data 事件 | 通过；最后单独验证 `[DONE]` |
| 3 个 VLM 请求由本机锁定版本的 Pydantic 模型校验 | 通过；未加载模型 |
| 图片示例 Base64 解码及 PNG 完整性 | 通过 |
| 8 个不符合监控口径的反例 | 均被 schema 拒绝 |
| NGINX 6 个精确 location 与契约清单核对 | 5 个 HTTP path 和 1 个 gRPC method 全部覆盖 |

监控反例包括错误的统计窗口、`not_deployed` 状态、异常状态携带旧指标、运行中缺少显存字段、
负显存、服务名与耗时类型不匹配、额外请求数量指标、负 P95。
监控列表中的部署真实性、服务名唯一性、采样时效需要实现层保证，不由 schema 单独判断。

校验环境建在临时目录，与 GPU 应用环境隔离。可在独立 CPU 虚拟环境中复现标准结构校验：

```bash
python3 -m venv /tmp/gpu-contract-review
/tmp/gpu-contract-review/bin/python -E -m pip install openapi-spec-validator==0.7.2
/tmp/gpu-contract-review/bin/python -E -m openapi_spec_validator contracts/openapi.yaml
```

结构和示例校验不等同于接口上线验收。已有网关/算法的真实调用记录仍见
[`gateway/docs/validation.md`](../gateway/docs/validation.md)。
监控实际实现、真实数据采集与 CPU 跨机调用，需要后续分别验收。

## BGE-M3 部署后的契约增量

同日新增 `/rag/health/ready`、`/rag/v1/models`、`/rag/v1/embeddings` 三个已实现操作，
新增从本机锁定 vLLM 导出的 5 个 RAG schema。当前契约版本为 `0.2.0-review`。

| 校验 | 结果 |
| --- | --- |
| `openapi-spec-validator==0.7.2` | 通过 |
| 全部 91 个 JSON Schema 结构与内部引用 | 通过 |
| 全部 16 个操作内请求/响应示例 | 通过 |
| NGINX 精确路由与契约清单 | 9 个 location = 8 个已实现 HTTP path + 1 个 gRPC method |
| 经网关返回的真实 RAG 模型列表和批量向量 JSON | 符合对应 200 响应 schema |
| RAG 真实行为、错误与上下文边界 | 6 项通过，见 RAG 验收记录 |

`/monitor/v1/overview` 继续保持 proposed；`/rag/v1/rerank` 继续预留并返回 404。
没有新增监控聚合、重排序、ASR 或 TTS 实现。
完整运行结果见 [`rag_service/docs/validation.md`](../rag_service/docs/validation.md)。

## Fun-ASR-Nano 实时接口增量

同日新增 `/asr/health/ready` 和 `/asr/v1/realtime`。OpenAPI 描述健康接口与 WebSocket 握手，
双向消息单列在 [`asr-websocket.md`](asr-websocket.md)；删除了完整文件转写预留路径。
当前契约版本为 `0.3.0-review`。

| 校验 | 结果 |
| --- | --- |
| `openapi-spec-validator==0.7.2` | 通过 |
| NGINX 配置语法及路由生成 | 通过 |
| 真实 NGINX + TLS + HTTP/SSE/WebSocket/gRPC 测试 | 13 项通过 |
| 真实 ASR WebSocket | partial、final、时间范围和 stopped 均通过 |
| 鉴权边界 | 公共入口缺 key 为 401；内部健康检查缺内部 key 为 401 |
| 不提供文件转写 | `/asr/v1/audio/transcriptions` 返回 404 |

ASR 真实行为与显存快照见 [`asr_service/docs/validation.md`](../asr_service/docs/validation.md)。

## CosyVoice 流式 TTS 增量

2026-09-11 新增 `/tts/health/ready`、`/tts/v1/audio/voices` 和
`/tts/v1/audio/speech`，从预留接口改为已实现操作。当前契约版本为 `0.4.0-review`。

| 校验 | 结果 |
| --- | --- |
| `openapi-spec-validator==0.7.2` 校验 OpenAPI 3.1.1 | 通过 |
| NGINX 配置语法、精确路由和密钥替换 | 通过 |
| 真实 NGINX + TLS + HTTP/SSE/WebSocket/gRPC 测试 | 14 项通过 |
| TTS 字段、PCM 格式、鉴权、取消清理、并发和日志脱敏单元测试 | 6 项通过 |
| 真实 CosyVoice 经统一入口生成 PCM/WAV | 通过 |
| 音色列表、错误公开 key、分词器控制序列拒绝 | 通过 |

TTS 返回固定 22050 Hz 单声道 PCM S16LE，使用 HTTP chunked 传输，不定义分块大小。
真实样本、首段时间与显存快照见
[`tts_service/docs/validation.md`](../tts_service/docs/validation.md)。监控仍未实现，TTS 的监控耗时
口径也尚未与现有 YOLO/VLM/RAG 指标契约合并。
