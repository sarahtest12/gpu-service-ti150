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
示例仍输出接口 JSON，答案在 `choices[0].message.content`，工具调用在 `choices[0].message.tool_calls`。
`client.py` 内部调用 `OpenAI(...).chat.completions.create()`，再把 SDK 响应转换为字典，保持原有示例的读取方式。
配置文件和命令行参数无需因本次迁移改变。`thinking` 通过 SDK 的 `extra_body` 传给 vLLM。

本客户端是同步非流式示例，显式设置 `max_retries=0`，每次调用只尝试一次；重试策略留给 CPU 业务层决定。
SDK 的超时配置作用于网络操作，不是整个业务流程的总时限；长请求取消、SSE 和会话存储尚未实现。
默认不使用环境代理，也不跟随 HTTP 重定向；请配置最终可达的服务入口。
客户端错误提示不包含服务端错误正文，避免输出文档或凭据；处理私密数据时不要启用 SDK 的调试日志。

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
