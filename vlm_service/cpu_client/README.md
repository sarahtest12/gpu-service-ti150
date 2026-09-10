# CPU 端接入

复制本目录即可使用，Python 3.10 及以上；客户端通过 OpenAI Python SDK 调用自建 vLLM 服务。
无需复制 GPU `.venv`、CoreX SDK 或模型，也无需 OpenAI 云端账号或云端 API Key。

## 安装依赖

在 CPU 应用自己的虚拟环境中，进入复制后的 `cpu_client` 目录执行：

```bash
python -m pip install -r requirements.txt
```

依赖清单固定本次验证使用的 OpenAI SDK 和 HTTPX 版本；不会安装 torch、vLLM 或显卡运行时。
本机 GPU 镜像已有这两个版本，开发测试直接复用；不要因此升级 GPU 镜像中的共享包。
此前的标准库客户端已被替换，现版本需要安装依赖，不能再使用 `python -S` 运行。

## 配置

将 `config.example.json` 复制为 `config.json`，把 `base_url` 改成 CPU 实际可达的 GPU HTTP 入口，例如：

```json
{
  "base_url": "http://GPU可达地址:8000/v1",
  "model": "qwen3.5-9b",
  "timeout_seconds": 180,
  "max_tokens": 512,
  "thinking": false
}
```

`VLM_BASE_URL` 环境变量可覆盖配置中的地址。`model` 使用服务别名，不使用权重路径。
如果 GPU 通过平台端口映射访问，地址和端口使用平台提供的入口；之前开通的 YOLO 50051 不会自动覆盖本服务的 8000。

通过私密渠道取得 GPU `runtime/api_key` 的内容并设置 `VLM_API_KEY`。令牌不放入 JSON 或源码。

PowerShell：

```powershell
$vlmSecureKey = Read-Host 'VLM API key' -AsSecureString
$env:VLM_API_KEY = [System.Net.NetworkCredential]::new('', $vlmSecureKey).Password
python demo.py --config config.json --image 'C:\资料\票据.png' --prompt '提取票据编号和金额，只输出 JSON'
```

Linux/WSL：

```bash
read -rsp 'VLM API key: ' VLM_API_KEY
export VLM_API_KEY
python3 demo.py --config config.json --image '/你的路径/票据.png' --prompt '提取票据编号和金额，只输出 JSON'
```

可重复 `--image` 传入两张图；不传图片时发送纯文本请求。文件路径相对当前工作目录解析。
默认输出接口 JSON，答案在 `choices[0].message.content`，工具调用在 `choices[0].message.tool_calls`。
`client.py` 内部调用 `OpenAI(...).chat.completions.create()`，再把 SDK 响应转换为字典，保持原有示例的读取方式。
配置文件和命令行参数无需因本次迁移改变。`thinking` 通过 SDK 的 `extra_body` 传给 vLLM。

客户端提供同步完整响应和同步 SSE 迭代接口，显式设置 `max_retries=0`，每次调用只尝试一次；
重试策略留给 CPU 业务层决定。SDK 的超时配置作用于网络操作，不是整个业务流程的总时限。
退出流式上下文会关闭 HTTP 响应；会话存储由 CPU 业务层管理。
默认不使用环境代理，也不跟随 HTTP 重定向；请配置最终可达的服务入口。
客户端错误提示不包含服务端错误正文，避免输出文档或凭据；处理私密数据时不要启用 SDK 的调试日志。

## 流式调用

同一个 `/v1/chat/completions` 接口在请求中设置 `stream: true` 即返回 SSE，服务端无需另开端口。
`stream_chat()` 已设置该参数，并请求最终 token 用量。命令行逐段打印答案、立即刷新输出：

```bash
python3 demo.py --config config.json --stream --prompt '请分三点介绍图片中的内容' --image '/你的路径/图片.png'
```

`--stream` 输出答案文本，默认模式输出完整 JSON；Ctrl+C 关闭本次连接。
如果中途报错，命令以非零状态退出，已经输出的文字应视为未完成答案。

后端接入使用上下文管理器，确保正常结束、提前 `break` 或异常时都关闭流：

```python
import os
from client import VlmClient

with VlmClient(os.environ['VLM_BASE_URL'], api_key=os.environ['VLM_API_KEY']) as client:
    with client.stream_chat([{'role': 'user', 'content': '请介绍一下自己'}]) as chunks:
        for chunk in chunks:
            for choice in chunk.get('choices', []):
                text = choice.get('delta', {}).get('content')
                if text:
                    print(text, end='', flush=True)
            if chunk.get('usage'):
                usage = chunk['usage']
```

每个 chunk 是标准 Chat Completions 增量字典，保留 `delta`、`finish_reason`、`usage` 和 vLLM 扩展字段。
最终用量块的 `choices` 可以为空。图片、`thinking`、`tools`、`tool_choice` 参数与 `chat()` 相同。
工具调用的名称和 JSON 参数可能分散在多个 chunk 中；CPU 按工具索引拼接，确认调用结束并完成白名单、
权限和参数校验后再执行。`stream_chat()` 不自动执行工具，也不自动把这些片段合成完整回答。

流中的超时、连接错误、服务端错误会转成脱敏的 `RuntimeError`，且不自动重试。
在收到 `finish_reason` 前遇到 EOF 或结束标记也会报错。`finish_reason=length` 表示生成已达 token 上限，
调用方应将其与正常的 `stop` 区分；取消或断流时不保证收到最终用量。

这是同步迭代器。异步 Web 后端需通过框架的线程池桥接同步流，或使用异步 SDK 实现同等关闭与错误处理；
不要在事件循环线程中直接执行阻塞迭代。浏览器断开时，CPU 后端应退出流式上下文，关闭到 GPU 的连接。
已进入 GPU 的计算何时停止由推理引擎处理，关闭客户端连接不承诺瞬间释放显存。

## Web 与反向代理转发

完整链路是 `VLM SSE → CPU 后端流式响应 → 浏览器逐段读取`。CPU 后端收到片段后即发送，
不要先收集成完整列表或调用完整响应的 JSON 读取；浏览器也需增量读取响应。
算法 API key 仅保存在 CPU 后端。统一网关接入后，`VLM_BASE_URL` 可设为 `http://GPU入口:端口/vlm/v1`。

如果链路中使用 NGINX，在已有流式路由的 `location` 内配置：

```nginx
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 180s;
```

`proxy_buffering off` 让上游片段到达后立即转发，避免 NGINX 将小片段暂存后成批发送；
它不改变模型生成速度，也不代表关闭日志或模型缓存。`proxy_read_timeout` 是两次上游读取之间的空闲时限，
不是整个生成过程的总时限，应按实际首段延迟配置。链路上的 GPU 网关和 CPU Web 代理都需要检查。
这些是流式路由配置项；当前仓库尚未部署统一网关或 CPU Web 应用。
参见 [NGINX 响应缓冲说明](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_buffering)
和 [OpenAI Chat Completions 参数](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create)。

## 业务工具示例

```bash
python3 tool_demo.py --config config.json --order-id DEMO-1001
```

模型自主生成 `get_order_status` 调用；CPU 检查工具白名单、参数键和订单编号格式，
读取内存中的演示数据，再发起第二次模型请求形成答案。
该示例只允许一次工具调用，结果明确标注 `source=demo`；不连接真实订单系统，不执行写操作。
未知工具和不合法参数立即拒绝，不执行模型生成的代码。

接入真实业务时，以受权限约束的只读 API 替换 `execute_readonly_tool()` 中的示例数据；
再按业务需求补充超时、审计、幂等与操作确认。不要把用户身份权限交给模型自行判断。

## 集成到后端

沿用 `VlmClient.chat()` 即可，底层已经是 SDK。短脚本使用 `with` 自动关闭连接；
长期运行的后端可复用一个客户端，在应用退出时调用 `close()`。

```python
import os
from client import VlmClient, image_part

with VlmClient(
    'http://GPU可达地址:8000/v1',
    api_key=os.environ['VLM_API_KEY'],
) as client:
    result = client.chat([{
        'role': 'user',
        'content': [image_part('扫描页.png'), {'type': 'text', 'text': '提取订单号和金额'}],
    }])
print(result['choices'][0]['message']['content'])
```

如果你的 CPU 后端已统一使用 OpenAI SDK，也可以直接调用，不依赖 `VlmClient`：

```python
import os
from openai import OpenAI, DefaultHttpxClient
from client import image_part

with OpenAI(
    base_url=os.environ['VLM_BASE_URL'],  # 例如 http://GPU可达地址:8000/v1
    api_key=os.environ['VLM_API_KEY'],
    timeout=180,
    max_retries=0,
    http_client=DefaultHttpxClient(trust_env=False, follow_redirects=False),
) as client:
    response = client.chat.completions.create(
        model='qwen3.5-9b',
        messages=[{'role': 'user', 'content': [
            image_part('扫描页.png'), {'type': 'text', 'text': '提取订单号和金额'},
        ]}],
        max_completion_tokens=512,
        extra_body={'chat_template_kwargs': {'enable_thinking': False}},
    )
    print(response.choices[0].message.content)
```

此方式返回 SDK 对象，使用属性访问；如需 JSON 字典，调用 `response.model_dump(mode='json', exclude_unset=True)`。
由你的后端负责捕获 SDK 异常、脱敏错误和统一配置。当前接入的是 Chat Completions，
不默认兼容 Responses、Files 等全部 OpenAI 接口。
SDK 的扩展参数、重试与资源关闭用法可查阅 [OpenAI 官方说明](https://developers.openai.com/api/reference/python)。
本项目的具体 API 以依赖清单锁定版本为准。

HTTP 层支持标准 `tools` 字段，详见 `tool_demo.py`。客户端不在 GPU 进程中执行工具。
图片只通过 Base64 发送，单张文件限制为 8 MiB；服务还会限制图片数和处理像素。

## 文档范围

已验证扫描页图片的字段抽取，不等同于完整 PDF 文档系统。
PDF 文本提取、扫描页渲染、页码溯源、跨页检索和批量文档管理应由 CPU 文档模块后续实现。
准确识别复杂表格或小字需要实际样本验收，不能用简单测试票据代替业务准确率评估。
