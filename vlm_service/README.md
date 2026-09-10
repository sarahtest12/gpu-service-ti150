# BI-V150 Qwen3.5 VLM 服务

使用天数适配版 vLLM 部署 `Qwen/Qwen3.5-9B`，为 CPU 智能体应用提供图片、文档页面和文本理解接口。
服务直接提供 vLLM 的 HTTP API，不包装新的推理协议；模型提出工具调用，CPU 应用执行工具。

## 环境与配置

本机部署配置的唯一来源是 [`config/server.json`](config/server.json)。
默认物理 GPU 1、BF16、单卡单并发、8K 上下文、最多两张图片，端口 8000。
视频输入关闭。8K 是首轮联调限制，不是模型自身的上下文上限；图片像素、页数和上下文需要一起规划。

`scripts/bootstrap.sh` 使用 Python 3.10 的 `--system-site-packages` 建立独立 `.venv`，
以只读方式复用当前镜像已经安装的 vLLM、ixformer、CoreX torch 和 Transformers。
这隔离了本项目新增的应用包，但不是独立封装 SDK；全局厂商包变动仍会影响本项目。
准确版本在 `scripts/service.py` 的环境检查中锁定，绝不能运行通用的 `pip install -U vllm/torch` 覆盖它们。

权重默认读取本机共享盘；客户部署时另行配置可信的本地模型目录，不能假设存在开发机共享盘。
首次复制到本地磁盘应检查完整性；本项目不会修改共享盘模型。

## 启动与停止

```bash
cd /home/mbwang/myproj/vlm_service
bash scripts/bootstrap.sh
.venv/bin/python scripts/service.py start
.venv/bin/python scripts/service.py status
```

`start` 立即返回后台进程信息，不代表模型已经就绪。`status` 的 `healthy: true` 才表示健康检查通过；
还应执行真实请求验收。首次加载权重和预热可能需要数分钟，日志路径在 status 输出中。

```bash
.venv/bin/python scripts/service.py stop
# 修改 config/server.json 后再启动：
.venv/bin/python scripts/service.py start
```

管理程序核对 PID 创建时间和项目归属，只向本项目进程组发送停止信号；不会停止 YOLO。
当前为后台进程模式，没有配置开机自启或故障自动恢复。容器中不能假设 systemd 可用。

## HTTP 接口与凭据

- `/health`：模型引擎健康状态；不替代真实推理验证。
- `/v1/models`：可用模型，需 Bearer token。
- `/v1/chat/completions`：文本、图片和工具调用，需 Bearer token；支持完整响应和 `stream: true` 的 SSE 流式响应。
- `/metrics`：vLLM 指标，限制到可信网络访问。

bootstrap 会生成 `runtime/api_key`（0600），该值通过 `VLLM_API_KEY` 环境变量传给服务，不出现在启动参数中。
CPU 端使用相同令牌；通过私密渠道传递，不贴在聊天、文档或源码里。
模型名称使用 `qwen3.5-9b`，而不是服务器上的模型文件路径。
本阶段为私网 HTTP 服务；跨不可信网络需另配 TLS 和入口访问控制，不能仅凭令牌直接公开。

图片使用 `data:image/...;base64,...`。远程媒体 URL 默认只允许保留域名 `media.invalid`，
实际用途是拒绝任意 URL 拉取；不开放本地媒体目录。需要其他来源时由 CPU 先读取图片并编码。
不支持直接上传 PDF 给本接口：电子 PDF 先在 CPU 提取文字，扫描件及图表先转成页面图片。
提取内容应保留页码；多页任务应分页、检索或分批，不能无限增加图片数。

普通交互可在请求中设置 `chat_template_kwargs: {"enable_thinking": false}`。
服务保留 `qwen3` 思考解析器和 `qwen3_coder` 工具解析器，是否调用工具由请求中的 tools 与提示词决定。

CPU 端复制 [`cpu_client/`](cpu_client/README.md) 并安装其中 `requirements.txt` 即可调用；
客户端使用 OpenAI Python SDK，提供图文请求、可编辑 JSON 配置和只读业务工具示例，不复制 GPU 环境。
流式调用使用 `with client.stream_chat(...) as chunks`；命令行加 `--stream` 即逐段显示文本。
上下文退出会关闭流，异常输出会脱敏。Web 后端转发、工具参数片段和 NGINX 缓冲配置见
[`cpu_client/README.md`](cpu_client/README.md#流式调用)。

## 验收

客户端离线测试使用真实 SDK 访问本地 HTTP 测试桩，无需 GPU 或令牌：

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_cpu*.py' -v
```

测试会向已运行的真实模型发送请求，不会另起模型实例或执行真实业务写操作：

```bash
RUN_VLM_INTEGRATION=1 .venv/bin/python -m unittest discover -s tests -p test_live_api.py -v
```

真实接口验收包括图文 SSE 增量、最终用量、工具参数增量、提前取消后的后续请求，以及原有的图片、文档和工具调用。
不设置开关时测试跳过，以免在无 GPU 或客户环境中意外发送请求。
本机已完成图片、文档字段和只读工具调用验收；结果与后续限制见 [`docs/validation.md`](docs/validation.md)。

## 目录与许可

- `config/`：非私密服务配置。
- `scripts/`：环境校验、初始化、进程管理。
- `tests/`：真实接口验收。
- `cpu_client/`：可复制到 CPU 后端的图文请求和只读工具示例。
- `runtime/`：本机私密文件与运行数据，不交付。

模型和 vLLM 上游均有各自许可证，客户交付须分别保留对应文件和声明。
本项目不把厂商 SDK 或共享盘权重打包进源码仓库。
