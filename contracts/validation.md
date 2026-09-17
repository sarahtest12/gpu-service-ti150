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
监控实现与真实数据采集见本文后续增量记录；CPU 跨机调用仍需在 CPU 服务器接入时验收。

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
[`tts_service/docs/validation.md`](../tts_service/docs/validation.md)。

## 五服务监控契约修订

2026-09-11 按 review 删除响应中的 `window_seconds`，统计窗口仍固定为最近 60 秒；把 ASR 和
TTS 加入服务枚举，两者都使用 `time_to_first_token`。ASR 统计每轮解码的首文本 token，TTS
统计首语音 token，均明确起止点和排除项。GPU 接口继续返回单次快照，由 CPU 后端每 5 秒拉取
并通过其与前端的长连接推送；手动刷新读取最新快照，不新增 GPU 长连接或强制采样参数。

随后接受手动刷新建议，增加可选查询参数 `refresh`：省略或为 false 时读取定时快照，true 时等待
一次立即采样；并发强制刷新允许合并。当前契约版本为 `0.5.1-review`。该修订只更新待实现契约和文档，
`/monitor/v1/overview` 仍返回 404。

## 五服务监控实现与验收

2026-09-11 将 `/monitor/v1/overview` 从 proposed 更新为 implemented，契约版本为 `0.6.0`。
监控进程每 5 秒采样，使用最近 60 秒的累计直方图增量，并通过 `ixsmi` 与进程父子关系归属显存。
ASR 从 vLLM `RequestOutput.metrics.first_token_latency` 取每轮解码首 token；TTS 在每个 HTTP 请求
第一次得到语音 token 时记录。两者的内部 `/metrics` 均要求各自内部 key，公网路径保持 404。

| 校验 | 结果 |
| --- | --- |
| 监控解析、进程/计数器重启、窗口淘汰、P95 与强制刷新合并 | 6 项通过 |
| TTS 请求、流式、鉴权与首 token 埋点 | 7 项通过 |
| 真实 NGINX + TLS + HTTP/SSE/WebSocket/gRPC/监控路由 | 15 项通过 |
| OpenAPI 3.1.1 与响应示例 | 通过 |
| 公共入口普通快照与 `refresh=true` | 均为 200，带 `no-store` 与请求 ID |
| 无公开 key / 非法 refresh / POST | 分别为 401 / 400 / 403 |

同一份真实快照中五个算法均为 `running` 并返回十进制 MB。该 60 秒窗口的样例值为：YOLO
8.735/9.875 ms、VLM 183.675/242.5 ms、RAG 46.031/285.0 ms、ASR 53.791/78.0 ms、
TTS 7478.046/9984.0 ms（依次为 avg/P95）。这些数值只验证采集链路和字段口径，不作为性能承诺。

## Fun-CosyVoice3 双向流式 TTS 契约

2026-09-17 将 TTS 公共契约替换为 `WSS /tts/v1/realtime`，契约版本升为 `0.7.0`。旧的三个
TTS 公共 HTTP 操作从 OpenAPI 和网关中删除；内部 `/health` 与 `/metrics` 继续只供本机监控使用。
双向 JSON、二进制 PCM、状态、错误和限制由 [`tts-websocket.md`](tts-websocket.md) 定义。

| 校验 | 结果 |
| --- | --- |
| OpenAPI 只暴露一个 TTS WebSocket 握手路径 | 通过 |
| 固定模型、音色、24 kHz PCM 和 utterance 级 TTFT 跨文档一致 | 通过 |
| TTS 引擎、WebSocket 服务、配置和 CPU 客户端 | 24 项通过 |
| 真实 NGINX/TLS WebSocket、公开 key 替换与单连接限制 | 通过 |
| 已移除 TTS 公共路径 | 使用正确公开 key 均返回 404 |

前面的 CosyVoice v1 HTTP 章节保留为 2026-09-11 的历史验收记录，不再描述当前公共接口。
