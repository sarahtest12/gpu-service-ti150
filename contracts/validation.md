# 契约校验记录

日期：2026-09-10。实现基线：`88bb84a`。本轮只创建契约文档，并为根 README 增加入口链接。
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
