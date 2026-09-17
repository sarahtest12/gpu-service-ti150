# 统一入口验收记录

日期：2026-09-10。环境：本机两张 BI-V150，YOLO GPU 0、Qwen3.5-9B VLM GPU 1，
NGINX 1.30.4。测试入口为 `https://localhost:8443`，使用开发证书和同一公开 key。
本记录不包含另一台 CPU 主机到 GPU 的网络连通性、正式域名证书或长时间吞吐压测。

## BGE-M3 接入后的增量验收

同日新增 BGE-M3（GPU 0、FP16）后，网关协议测试扩展为 12 项，全部通过；
包含 RAG 路由、独立内部 key、鉴权、请求体/并发限制、失败隔离及配置检查失败时保留原配置。
原有 3 项网关真实模型验收通过，RAG 新增 6 项真实接口验收通过。
RAG 与 YOLO、VLM 共存及 RAG 独立停启验证通过，详见
[`../../rag_service/docs/validation.md`](../../rag_service/docs/validation.md)。
加入 ASR 后五个服务保持运行。下面“全部停止”的描述是首次网关验收时的历史状态。

## Fun-ASR-Nano 实时接口增量验收

同日部署 Fun-ASR-Nano-2512 后，五个服务进程组均保持 `ready: true`。网关协议测试增加
WebSocket 用例后为 13 项，验证了 TLS 升级、公共 key 替换为 ASR 内部 key、partial/final
双向消息、ASR 独立并发限制、健康检查和错误公共 key。

真实模型使用 100 ms PCM16 帧回放 5.616 秒样例，约 2.15 秒出现首个非空 partial，结束后返回
“开饭时间早上九点至下午五点。”以及 420–5610 ms 时间范围。NGINX 关闭 ASR 代理缓冲并保持
WebSocket Upgrade。完整文件转写路径经验证返回 404。详细结果见
[`../../asr_service/docs/validation.md`](../../asr_service/docs/validation.md)。

## CosyVoice 流式 TTS 增量验收

2026-09-11 部署 CosyVoice-300M-Instruct 后，网关、YOLO、VLM、RAG、ASR、TTS 六个进程组
均为 `managed: true`、`ready: true`。网关协议测试扩展为 14 项，验证 TTS 公共 key 被替换为
独立内部 key、PCM 首段不会等待上游完成、并发 1 的额度不阻塞 VLM、16 KiB 请求体限制、
健康和音色接口，以及 docs/metrics/模型列表等未开放路径保持 404。

真实模型通过 `https://localhost:8443` 合成 2.299 秒 WAV，首段约 8.969 秒、总耗时约
8.974 秒。模型与网关均未在响应中提供 `Content-Length`，CPU 客户端按返回头将分块 PCM
封装为有效 WAV。详细运行时、显存和限制见
[`../../tts_service/docs/validation.md`](../../tts_service/docs/validation.md)。

## 五服务监控增量验收

2026-09-11 增加独立监控进程后，网关、五个算法和监控共七个进程组均为
`managed: true`、`ready: true`。网关协议测试扩展为 15 项，新增验证公共 key 被替换为监控内部
key、`refresh=true` 查询参数保留、`Cache-Control: no-store` 和方法限制。

真实入口 `/monitor/v1/overview?refresh=true` 返回五个 `running` 服务。显存能同时归属 ASR/RAG/VLM
的 vLLM EngineCore 子进程；YOLO、VLM、RAG、ASR、TTS 的 60 秒耗时均通过各自真实请求产生并返回。
完整字段和值记录在 [`../../contracts/validation.md`](../../contracts/validation.md)。

## 首次网关验收结果（历史）

| 验证 | 结果 |
| --- | --- |
| 真实 NGINX + TLS + HTTP/SSE/gRPC 测试桩 | 9 项通过 |
| 统一入口真实模型验收 | 3 项通过 |
| 原有 VLM 图片、文档、工具和流式验收经网关运行 | 6 项通过 |
| VLM 客户端本地 HTTP/SSE 测试 | 17 项通过 |
| YOLO 服务现有测试 | 19 项通过，1 项显式 GPU 加载测试未启用而跳过 |
| YOLO CPU 客户端现有测试 | 6 项通过 |

共 60 项通过、1 项跳过。真实 YOLO 模型另由统一入口验收覆盖：过期帧返回 `EXPIRED`，
同一双向流的下一张有效图片返回 `OK` 且有检测框。错误公开 key 返回 `UNAUTHENTICATED`。

网关协议测试验证了 key 大小写敏感、内部 key 不能用于外部入口、上游令牌替换、请求 ID、
TLS 信任校验、未知路由、请求体限制、独立并发额度、错误状态、禁止自动重试、
首段 SSE 在上游完成前到达、HTTP 与 gRPC 取消传递，以及单个上游不可用时的隔离。

真实 VLM 图文 SSE 一次联调收到 26 个文本片段，首个文本约 0.270 秒，总计约 1.809 秒；
收到 `finish_reason=stop` 与最终用量。这只是简单样例的一次记录，不作为性能承诺。
工具参数增量、取消后继续请求、扫描票据字段提取、只读业务工具闭环均通过。

另外进行了真实进程的独立停启验证：停止 YOLO 时，网关和 VLM 就绪接口仍返回 200，
VLM 可继续流式生成，YOLO 就绪接口返回 502；重新启动 YOLO 后恢复就绪。
停止 VLM 时，网关和 YOLO 就绪接口仍返回 200，VLM 就绪接口返回 502。
此时 YOLO 的 CPU CLI 使用 TLS、共享 key、相对配置目录的证书路径，从其他工作目录发送
2 帧图片，均收到 `OK` 和检测框。旧 YOLO token 故意设置错误，证明新 `GPU_API_KEY` 优先。
网关也已独立停止、重新启动并恢复就绪，YOLO 进程保持运行。
验收后恢复三个服务全部停止的状态；8443、8000、50051、8081 均无监听，
本管理器拥有的进程已全部退出，`ixsmi` 报告两张 GPU 均无运行进程。

## 复现

以下命令从仓库根目录执行。先按网关 README 准备环境、权重、凭据和证书。
测试不输出 key；不要启用 shell 跟踪或 SDK 调试日志。

无需启动真实模型的网关测试：

```bash
source yolov5v70-service/scripts/corex_env.sh
python -m unittest discover -s gateway/tests -p test_gateway.py -v
```

真实模型验收使用已经运行的进程，不另起模型实例：

```bash
python3 gateway/service.py start
python3 gateway/service.py status
# 等待七个服务均 ready: true 后：
source yolov5v70-service/scripts/corex_env.sh
RUN_GATEWAY_INTEGRATION=1 python -m unittest discover -s gateway/tests -p test_live_gateway.py -v
```

通过统一入口执行 VLM 完整验收：

```bash
python3 - <<'PY'
import os
from pathlib import Path
import subprocess

root = Path.cwd()
env = os.environ.copy()
env.update(
    RUN_VLM_INTEGRATION="1",
    VLM_BASE_URL="https://localhost:8443/vlm/v1",
    GPU_API_KEY=(root / "gateway/runtime/api_key").read_text().strip(),
    GPU_CA_FILE=str(root / "gateway/runtime/tls/server.crt"),
)
raise SystemExit(subprocess.call([
    str(root / "vlm_service/.venv/bin/python"), "-m", "unittest", "discover",
    "-s", "tests", "-p", "test_live_api.py", "-v",
], cwd=root / "vlm_service", env=env))
PY
```

更换端口、证书或目标名称后，相应调整上面这段验收配置。
VLM 本地客户端测试在 `vlm_service/` 执行：

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_cpu*.py' -v
```

YOLO 服务测试在 `yolov5v70-service/` 执行：

```bash
source scripts/corex_env.sh
NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost python -m unittest discover -s tests/gpu_detector -v
```

本机环境代理会接管旧健康检查测试中的 `urllib` 请求，因此测试命令显式排除本机地址。
网关管理器和 VLM 客户端自身已禁用环境代理，不依赖该设置。
YOLO CPU 客户端测试在其 `cpu_client/` 目录执行 `python -m unittest discover -s tests -v`。

## 部署边界

本次构建并安装了项目内 NGINX，补齐主机的 PCRE2 构建依赖；没有改动厂商 CoreX/vLLM 包。
YOLO 独立虚拟环境已建立，官方 v7.0 权重下载后通过仓库指定 SHA-256 校验。
开发凭据、证书、模型、编译输出与私密运行日志均在 Git 忽略范围内。

未安装或启用 systemd 单元；提供的是需要按实际部署路径、用户调整的模板。
RAG rerank 与 YOLO HTTP 单图路由尚未实现，当前不会伪装成可用服务。
ASR 仅部署实时 WebSocket，不提供完整文件转写路由。

## Fun-CosyVoice3 双向流式路由验收

2026-09-17 网关将 TTS 公共入口替换为 `WSS /tts/v1/realtime`。真实 NGINX/TLS 测试桩验证了
WebSocket Upgrade、统一公开 key 替换为 TTS 内部 key、二进制 PCM 不缓冲、单连接 429 限制、
TTS 长连接不阻塞 VLM，以及已移除的 TTS 公共路径返回 404。网关全量协议测试 15 项通过，
常规测试中 4 项需要运行中模型的验收按环境开关跳过；切换完成后设置
`RUN_GATEWAY_INTEGRATION=1` 单独执行，YOLO、VLM、ASR 和统一健康/鉴权 4 项全部通过。

内部 TTS 报告就绪后才重载 NGINX；重载后网关和五个算法及监控进程均为
`managed: true`、`ready: true`。CPU 客户端通过 `wss://localhost:8443/tts/v1/realtime` 建立一个
连接，事件序列为 `session.created`，每条 utterance 的 `audio.start`、二进制 PCM、
`audio.done`，最后 `session.close`。三条语音的结果如下：

| utterance | 首个 PCM | 总耗时 | 音频时长 | PCM SHA-256 |
| --- | ---: | ---: | ---: | --- |
| 1（文本三段追加） | 1.829533 s | 19.530475 s | 18.120000 s | `bcb78c973e7c1133e2634724e2a8c9f1c0f780416c10200c6027c022816b1330` |
| 2（复用连接） | 1.518033 s | 10.818417 s | 11.280000 s | `1b429c3f5fd2f6e1a84f56e5cf12cbd54a44f6d622f604b1668523ce72d71802` |
| 3（复用连接） | 1.531372 s | 12.901734 s | 12.520000 s | `ead95293172bcccd9f67b71eec585cb249cb15e60940851bcdc45dcae1e905b6` |

第一条在发送三段文本后保持 generator 打开，收到首个二进制 PCM 后才允许发送 `input.done`，
因此双向流式通过公共 NGINX/TLS 路径得到验证。`/tts/v1/audio/speech`、
`/tts/v1/audio/voices`、`/tts/health/ready` 使用正确公开 key 均返回 404。强制监控快照返回 TTS
`running`、显存 4034.920 MB、近 60 秒 TTFT 平均 124.039 ms、P95 296 ms。真实模型和
CoreX 兼容补丁见
[`../../tts_service/docs/validation.md`](../../tts_service/docs/validation.md)。
