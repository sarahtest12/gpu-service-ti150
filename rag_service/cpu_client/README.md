# CPU 后端调用 BGE-M3

此目录可独立复制到 CPU 后端项目；不需要 GPU、torch 或天数 SDK。
先安装 `requirements.txt`，复制 `config.gateway.example.json` 为本地 `config.json`，
将 `GPU_HOST` 替换为 GPU 服务器地址，将证书放在配置旁。
`ca_file` 相对配置文件解析，`GPU_CA_FILE` 可覆盖它；使用系统信任的证书时删除 `ca_file`。
证书必须覆盖 GPU 目标地址，本机现有开发证书仅覆盖 localhost/127.0.0.1。

通过安全配置注入 `GPU_API_KEY` 环境变量，与 VLM/YOLO 使用相同的公开 key。
不复制 GPU 上的内部 key 或 TLS 私钥。客户端验证 TLS，关闭环境代理、重定向和自动重试。

```bash
python -m pip install -r requirements.txt
python demo.py --config config.json --text '忘记密码后应该怎么办？' --text '员工可以通过验证码重置密码。'
```

Python 调用（`rag_client.py` 放在可导入路径）：

```python
import os
from rag_client import RagClient

with RagClient(
    "https://GPU_HOST:8443/rag/v1",
    api_key=os.environ["GPU_API_KEY"],
    ca_file="/path/to/server.crt",
) as client:
    result = client.embed(["第一段文档", "第二段文档"])
    vectors = [item["embedding"] for item in result["data"]]
```

`embed()` 接受非空文本或非空文本数组，返回 OpenAI 风格字典，保留 `data` 与 `usage`。
每个向量固定 1024 维，显式要求归一化；校验返回数量、顺序、维度和有限数值。
请求失败抛出脱敏的 `RuntimeError`，不把上游响应正文或凭据直接展示给前端。
当前单段上限为 2048 tokens（含特殊 token）；建议文档先按 512–1024 tokens 分块，
每次最多提交 16 段。服务端不额外强制这个建议批量数，但限制请求体 256 KiB 和引擎工作批量。

业务流程：文档分块并编码入库；问题编码后执行向量检索；选取相关片段调用 VLM 生成回答。
向量数据库与业务权限由 CPU 项目选择和实现。当前不执行重排序，也不把文档持久化到 GPU 服务。
