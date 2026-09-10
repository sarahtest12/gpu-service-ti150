# BGE-M3 部署验收

日期：2026-09-10。模型 `BAAI/bge-m3`，物理 GPU 0，与 YOLO 共用。
环境版本与执行限制见 [`../README.md`](../README.md)；本次没有升级厂商包。
测试通过 `https://localhost:8443`，使用同一公开 API key 和校验证书的客户端。
以下结果是本机短时验证，不包含 CPU 服务器跨机网络、长时间负载或业务知识库召回率评测。

## 接口与生命周期

| 验证 | 结果 |
| --- | --- |
| 厂商包版本、导入与本地模型/tokenizer 配置 | 通过 |
| 网关真实 NGINX/TLS/HTTP/gRPC 测试桩 | 12 项通过 |
| BGE-M3 真实接口 | 6 项通过 |
| 原有网关 YOLO 与 VLM 真实调用 | 3 项通过 |
| GPU FP16 向量与 Transformers CPU FP32 对照 | 通过，两个样本余弦相似度均大于 0.999999 |
| RAG 单独停止、重新启动与恢复调用 | 通过 |
| OpenAPI 3.1.1、schema、示例与真实响应校验 | 通过 |

RAG 六项验收覆盖：

- 中文及中英跨语言问题正确匹配重置密码段落，排在报销与食谱负样本之前。
- 批量和单独编码一致，返回顺序正确，1024 维、有限数值、L2 范数约 1。
- JSON float 与 Base64 解码结果一致。
- 模型列表、健康检查、缺少/错误 key 与未开放的 rerank/metrics 路由。
- 错误模型、错误输入类型、512 维请求、超长 token 输入、过大请求体被拒绝；之后仍可正常请求。
- 配置的 2048-token 边界可推理；CPU CLI 在 `/tmp` 工作目录下正常运行。

CPU FP32 对照使用同一份模型权重、tokenizer、CLS pooling 和 L2 归一化。
与 GPU FP16 vLLM 输出的余弦相似度为 0.99999946 / 0.99999923，最大元素绝对差约 0.000203。
这是数值实现一致性检查，不能替代业务检索效果评测。

新增路由通过网关重载接入。YOLO、VLM 和 NGINX 主进程保持原 PID。
单独停止 RAG 时 `/rag/health/ready` 返回 502，YOLO/VLM 就绪和网关存活仍为 200；
重启 RAG 后六项真实接口验收再次通过。未重启 YOLO/VLM，未部署 reranker。
验收完成后网关、YOLO、VLM、RAG 均保持运行、就绪；状态以 `gateway/service.py status` 为准。

## 共存短时样本

使用 [`../tests/coexistence_probe.py`](../tests/coexistence_probe.py)：
YOLO 先单独处理 40 帧，再在两个 RAG HTTP 请求循环并发时处理 80 帧，两阶段均按 10 FPS 发送。
每个 RAG 请求提交 4 段相同长度的中文测试文本，每段由示例句重复 16 次。
共完成 170 个 RAG HTTP 请求、680 段文本；同时 VLM 完成一次 27 个文本片段的 SSE 回答，
`finish_reason=stop`。120 帧 YOLO 全部 `OK` 且有检测框。

| 耗时口径 | 样本数 | 平均 ms | P95 ms | 最大 ms |
| --- | --- | --- | --- | --- |
| YOLO 单独运行：服务返回的模型推理耗时 | 40 | 7.540 | 8.081 | 8.237 |
| YOLO 与 RAG 并发：服务返回的模型推理耗时 | 80 | 8.197 | 11.218 | 12.710 |
| YOLO 单独运行：客户端完整往返 | 40 | 41.538 | 43.821 | 45.234 |
| YOLO 与 RAG 并发：客户端完整往返 | 80 | 52.685 | 61.076 | 80.342 |
| RAG：客户端 HTTP 完整往返，每请求 4 段 | 170 | 104.679 | 118.669 | 865.250 |

RAG 这里的耗时包括客户端序列化、TLS/HTTP、排队、模型与响应处理，**不是 GPU 纯推理耗时，也不是已部署的 60 秒监控**。
包含首批请求，没有删除较慢样本；P95 使用样本最近秩法。该测试证明此负载下能共存，
也显示 YOLO 延迟有上升，不能据此承诺任意视频路数或 RAG 并发量。

每秒通过 `ixsmi` 采样的进程显存最高值（MB=1000000 bytes）：

| 服务 | 设备 | 采样最高 MB |
| --- | --- | --- |
| BGE-M3 引擎 | GPU 0 | 2325.742 |
| YOLO | GPU 0 | 201.327 |
| VLM 引擎 | GPU 1 | 28277.998 |

这是进程显存采样，可能漏掉更短暂的峰值。RAG 原始显示为 2218 MiB；与日志中的约 1.06 GiB
模型权重占用不同，服务还需要激活、工作区等显存。`gpu_memory_utilization=0.15` 不应解释为进程硬限额。

## 复现

```bash
python3 gateway/service.py status
RUN_RAG_INTEGRATION=1 rag_service/.venv/bin/python -m unittest discover -s rag_service/tests -p test_live_api.py -v
source yolov5v70-service/scripts/corex_env.sh
python -m unittest discover -s gateway/tests -p test_gateway.py -v
RUN_GATEWAY_INTEGRATION=1 python -m unittest discover -s gateway/tests -p test_live_gateway.py -v
RUN_RAG_INTEGRATION=1 python rag_service/tests/coexistence_probe.py
```

当前证书只覆盖 localhost/127.0.0.1。CPU 主机接入须使用可达的 GPU 地址与覆盖该地址的证书。
启动日志中存在厂商 eager/图优化关闭、SWIG/websockets 弃用与 ZMQ 资源警告，本次未发现阻断推理的异常。
超长输入反例会在 vLLM 日志留下 `VLLMValidationError` 和 traceback，HTTP 返回预期的 400；
这是拒绝 2049-token 输入的验收记录，随后正常请求继续成功，不是引擎崩溃。
