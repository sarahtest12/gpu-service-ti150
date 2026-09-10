# BGE-M3 向量服务

使用当前天数适配版 vLLM 在物理 GPU 0 部署 `BAAI/bge-m3`，与 YOLO 共用设备。
CPU 后端通过统一 HTTPS 入口调用，与 YOLO、VLM 共用端口和 `GPU_API_KEY`。
本阶段只部署 dense embedding。文档解析、分块、向量数据库、召回与权限在 CPU 后端实现，
回答生成复用 VLM；没有新增 reranker 模型。

## 配置与环境

[`config/server.json`](config/server.json) 是模型运行配置的唯一来源：

| 配置 | 当前值 |
| --- | --- |
| 模型目录 | `/share/fshare/common/models/BAAI/bge-m3` |
| 对外模型别名 | `bge-m3` |
| 设备 / 精度 | GPU 0 / FP16 |
| 内部监听 | `127.0.0.1:8002` |
| 输出 | 默认 CLS pooling + L2 归一化，1024 维 |
| 每段输入上限 | 2048 tokens，含特殊 token |
| 引擎单轮限制 | 最多 4 段、共 2048 tokens |
| 显存参数 | `gpu_memory_utilization=0.15`；不是进程级显存硬隔离 |
| 执行模式 | pooling runner、eager、单卡 |

模型原生支持 8192 tokens；当前 2048 是与 YOLO 共存的首版服务限制。完整文档应先分块。
修改长度、批量或精度后需要重新验证峰值显存、向量质量及 YOLO 延迟。
网关最多接收 4 个活跃向量请求，请求体上限 256 KiB，上游空闲读取超时 60 秒；
这些值在 `gateway/config/server.json` 的 `rag` 中配置。
引擎批量限制不等于 HTTP 数组长度限制；建议 CPU 每个请求最多提交 16 段，服务未额外强制该数量。

独立 `.venv` 通过 `--system-site-packages` 只读复用镜像中的厂商包。
`scripts/service.py check` 校验实际锁定的 vLLM、ixformer、CoreX torch、Transformers 版本及模型配置。
不要运行通用的 `pip install -U torch/vllm`，也不要为此服务升级现有 VLM 环境。
当前权重在共享盘；客户交付需配置可信的本地模型目录，保留模型许可证并核验复制完整性。

## 准备和管理

从仓库根目录执行；网关本身按 [`gateway/README.md`](../gateway/README.md) 初始化。

```bash
bash rag_service/scripts/bootstrap.sh
python3 gateway/service.py start --service rag
python3 gateway/service.py status
python3 gateway/service.py reload --service gateway
```

`start` 只表示进程已启动，`ready: true` 才表示模型引擎就绪。首轮初始化可能需要约一分钟。
`reload` 检查配置后让已运行的网关接入新增路由，不重新加载 YOLO/VLM 模型；应继续检查新路由。
首次启动网关用 `start --service gateway`。`start/status/stop` 不加 `--service` 时包含已配置的 RAG。

```bash
python3 gateway/service.py stop --service rag
python3 gateway/service.py start --service rag
```

RAG 的 PID、创建时间与日志由网关管理器记录在 `gateway/runtime/`；内部 key 在
`rag_service/runtime/api_key`，仅供网关注入上游请求。公开 key 与 RAG 内部 key 不相同。
不要打印、提交或复制内部 key 给 CPU 客户端。
生产可使用现有 `gpu-algorithm@rag.service` 模板实例；当前后台模式没有开机自启或故障自动恢复。

## 接口

| 方法 | 统一入口路径 | 用途 |
| --- | --- | --- |
| POST | `/rag/v1/embeddings` | 文本 / 文本数组编码 |
| GET | `/rag/v1/models` | 模型别名与服务上下文上限 |
| GET | `/rag/health/ready` | 引擎就绪；200/503 空响应体 |

三个路径都要求 `Authorization: Bearer <GPU_API_KEY>`。`/rag/v1/rerank` 仍返回 404。
网关按精确路径转发，不公开 RAG 的 `/metrics`、`/pooling`、`/tokenize` 或管理接口。
监控聚合服务仍是待实现的设计；此处健康检查不代表已经部署显存与最近 60 秒耗时监控。

请求示例：

```json
{
  "model": "bge-m3",
  "input": ["忘记密码后应该怎么办？", "员工可以通过手机验证码重置密码。"],
  "encoding_format": "float"
}
```

返回标准 OpenAI 风格的 `object: list`、`model`、`data`、`usage`，以及 vLLM 的 `id`、`created`。
`data[i].index` 对应输入位置，`data[i].embedding` 是 1024 个数值；`usage` 汇总输入 token 数，
不是耗时。默认返回 JSON 数值数组；`base64` 输出及对应 tokenizer 的 token ID 输入也已验证。
完整协议字段见 [`contracts/openapi.yaml`](../contracts/openapi.yaml) 的 RAG 操作和 schema。

入库与查询必须使用同一模型及预处理。BGE-M3 无需为查询添加检索指令。
保持默认归一化，可在 CPU 向量库使用余弦相似度，或对归一化向量使用点积。
不要设置 `use_activation=false`，否则上游会返回未归一化向量。
不要指定较小的 `dimensions`；BGE-M3 不提供本部署下的可变维度输出。
超长输入默认返回 400；CPU 客户端不静默截断。未知模型返回 404，错误 key 返回 401，
过大请求体返回 413，并发超过网关限制返回 429，上游停止时通常返回 502。

## CPU 客户端与验证

复制 [`cpu_client/`](cpu_client/README.md) 到 CPU 项目，只有 OpenAI SDK/HTTPX 依赖。
接口保持非流式；向量结果完成后一次返回 JSON，回答生成的流式调用仍由 VLM 提供。

```bash
RUN_RAG_INTEGRATION=1 rag_service/.venv/bin/python -m unittest discover -s rag_service/tests -p test_live_api.py -v
# 共存探测还需要 YOLO 的共享 protobuf、gRPC 和 Pillow；复用其环境：
source yolov5v70-service/scripts/corex_env.sh
RUN_RAG_INTEGRATION=1 python rag_service/tests/coexistence_probe.py
```

测试请求已有服务，不另起模型。共存探测仅输出短时样本的客户端耗时、YOLO 模型推理耗时与
每秒采样的进程显存峰值，不是常驻监控或容量承诺。实际结果见 [`docs/validation.md`](docs/validation.md)。

依据：[BGE-M3 官方模型卡](https://huggingface.co/BAAI/bge-m3)、
[vLLM 0.17 pooling](https://docs.vllm.ai/en/v0.17.0/models/pooling_models/)。
