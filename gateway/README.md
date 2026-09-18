# 统一算法入口

NGINX 在同一 TLS 端口承载 HTTP/1.1 和 HTTP/2：VLM 通过 HTTP/SSE，RAG 与监控通过 HTTP
JSON，ASR 与 TTS 通过 WebSocket，YOLO 通过原生 gRPC 双向流。
默认监听所有网卡的 `8443`，不设置调用方 IP、域名或 Origin 白名单。所有公开路径，包括状态接口，
都校验 `Authorization: Bearer <GPU_API_KEY>`。网络平台或防火墙仍需放行这个端口。

## 首次准备

从仓库根目录运行。网关控制程序只使用 Python 3 标准库，NGINX 安装在本项目 `runtime/`。
构建前需要 `gcc`、`make`、`curl`、`pkg-config`，以及 OpenSSL、PCRE2、zlib 开发头文件。
Ubuntu 可安装 `build-essential libssl-dev libpcre2-dev zlib1g-dev`；这些是网关构建依赖。

```bash
bash gateway/bootstrap.sh
python3 gateway/service.py init --name GPU的实际IP或域名
python3 gateway/service.py check
```

bootstrap 固定 NGINX 1.30.4 并校验源码 SHA-256，启用 SSL 与 HTTP/2，不修改厂商 SDK。
构建日志在 `gateway/runtime/build/`。已有二进制时保留它；NGINX 升级应在停止网关后更新固定版本和校验值，
重新构建并执行网关验收。

`init` 仅为不存在的文件生成凭据和开发证书，重复运行保留已有文件。开发证书有效期 30 天，包含
`localhost`、`127.0.0.1` 和所有 `--name` 指定的 GPU **目标地址**，可重复传入 `--name`。
证书名称校验与限制调用方来源无关。正式部署可在配置中指定已有的证书链和私钥；证书应包含客户端使用的目标地址。
更换地址或证书时，替换配置指向的证书/私钥后重启网关。调用方始终校验证书，不提供跳过验证开关。
`probe_host` 是管理器检查网关时使用的目标，默认 `localhost`；更换为正式证书后，应设置为
本机可达且包含在该证书中的 GPU 名称或 IP。它不控制监听地址，也不是调用方白名单。

密钥文件默认位置：

| 文件 | 用途 |
| --- | --- |
| `gateway/runtime/api_key` | CPU 后端唯一持有的算法 key |
| `gateway/runtime/yolo_api_key` | 网关注入 YOLO 请求，同时传给 YOLO 进程 |
| `vlm_service/runtime/api_key` | 保留 VLM 自己的内部 key，网关注入上游请求 |
| `rag_service/runtime/api_key` | RAG 内部 key，网关注入上游请求 |
| `asr_service/runtime/api_key` | ASR 内部 key，网关在 WebSocket 握手时注入 |
| `tts_300m_service/runtime/api_key` | 默认 TTS 内部 key，网关注入上游请求 |
| `monitor_service/runtime/api_key` | 监控内部 key，网关注入上游请求 |
| `gateway/runtime/tls/server.crt` | 可传给 CPU 客户端信任的开发证书 |
| `gateway/runtime/tls/server.key` | 留在 GPU 主机的 TLS 私钥 |

密钥和私钥权限为 0600。生成的 `runtime/nginx.conf` 含上游与公开凭据，也为私密文件；
不要将 runtime 目录放入 Git、交付包或使用 `nginx -T` 输出它。脚本只输出文件位置，不输出令牌。
key 轮换需要更新对应文件后重启；公开 key 只需重启网关，内部 key 需要同时重启对应算法和网关。

## 准备算法

YOLO、VLM、RAG 和 ASR 的环境仍由各自 bootstrap 管理。YOLO 默认权重是官方 v7.0 的 `yolov5s.pt`，
位置 `yolov5v70-service/models/yolov5s.pt`，不进入 Git。准备权重后运行环境检查：

```bash
mkdir -p yolov5v70-service/models
# 仅在尚未准备权重时下载；已有业务权重应先配置其路径与校验值。
curl --fail --location --proto '=https' \
  https://github.com/ultralytics/yolov5/releases/download/v7.0/yolov5s.pt \
  -o yolov5v70-service/models/yolov5s.pt
printf '%s\n' '8b3b748c1e592ddd8868022e8732fde20025197328490623cc16c6f24d0782ee  yolov5v70-service/models/yolov5s.pt' | sha256sum --check
bash yolov5v70-service/scripts/bootstrap_corex.sh
bash vlm_service/scripts/bootstrap.sh
bash rag_service/scripts/bootstrap.sh
bash asr_service/scripts/bootstrap.sh
bash tts_300m_service/scripts/bootstrap.sh
python3 monitor_service/scripts/service.py check
```

VLM 模型路径见 `vlm_service/config/server.json`。统一管理目前按本机分配固定 GPU 0 给 YOLO、GPU 1 给 VLM，
YOLO 使用上述验收权重。换业务模型需更新网关配置中 `yolo.weights` 和 `yolo.weights_sha256`，
并通过 YOLO 环境变量配置匹配的类别文件等参数，重新做检测验收。
RAG 的模型配置见 `rag_service/config/server.json`，BGE-M3 在 GPU 0 以 FP16 与 YOLO 共存。
ASR 配置见 `asr_service/config/server.json`，Fun-ASR-Nano 在 GPU 0 使用 BF16 和 vLLM 解码。
默认 TTS 配置见 `tts_300m_service/config/server.json`。CosyVoice-300M-Instruct 使用 CoreX
FP16 + JIT 分段 FIFO，在 GPU 0 运行。原 `tts_service` 已恢复为 Fun-CosyVoice3 双流服务并保留，
但网关管理器不会默认启动它；两个目录都使用 8004，因此不能同时运行。
VLM/RAG/ASR/TTS 的监听配置须与网关各自的上游地址一致；算法内部端口仅监听 loopback。
删除网关配置中的 `rag` 段可不管理或转发 RAG；这不会主动停止已运行的 RAG，应先单独停止它。

## 启动、状态和停止

```bash
python3 gateway/service.py start
python3 gateway/service.py status
python3 gateway/service.py stop --service vlm
python3 gateway/service.py start --service vlm
python3 gateway/service.py stop --service rag
python3 gateway/service.py start --service rag
python3 gateway/service.py stop --service asr
python3 gateway/service.py start --service asr
python3 gateway/service.py stop --service tts
python3 gateway/service.py start --service tts
python3 gateway/service.py stop --service monitor
python3 gateway/service.py start --service monitor
python3 gateway/service.py reload --service gateway
python3 gateway/service.py stop
```

`--service tts` 固定管理 `tts_300m_service`。更换为保留的 CosyVoice3 属于运维配置变更，需要先
停止当前 TTS，再同时修改 `gateway/service.py` 的项目映射和 `gateway/config/server.json` 的内部
key 路径，启动目标服务、重启 monitor 并 reload 网关；monitor 会在启动时读取各算法内部 key，
未重启会把新 TTS 的 401 误报为 `error`。切换期间已有连接会断开，新握手可能返回 502/504。

七个服务进程组各有独立日志和状态记录。启动时模型可能仍在加载；网关可以先服务其他已就绪算法。
`reload` 只重载网关：先验证候选配置，通过后原子替换配置并发送 HUP。失败时保留原配置，
不会重启算法进程。重载返回后仍需验证新路由；旧 worker 的最长退出等待为 10 秒。
`managed` 表示本控制程序拥有该后台进程，`ready` 表示相应接口检查通过，两者分别报告。
`/health/live` 只表示网关存活；公开的算法就绪路径包括 `/vlm/health/ready`、
`/yolo/health/ready`、`/rag/health/ready` 和 `/asr/health/ready`。TTS 状态由本机监控服务通过
内部 `/health` 采集，不再公开独立的 TTS 健康路径。
本地管理器用 PID 创建时间及项目归属校验进程，停止操作只作用于本次启动的进程组。
使用该管理器启动后，也用它停止；不要混用算法目录的后台启动脚本或生产 systemd。

开发后台模式没有自动恢复。需要开机自启和故障恢复的 systemd 主机，可以使用
`deploy/gpu-algorithm@.service`，按实际安装路径和专用运行用户调整，保证其能读取模型和设备、拥有 runtime。
分别启用 `gpu-algorithm@gateway`、`gpu-algorithm@yolo`、`gpu-algorithm@vlm`、`gpu-algorithm@rag`、`gpu-algorithm@asr`、`gpu-algorithm@tts` 和 `gpu-algorithm@monitor` 实例。
模板的 `run --service ...` 在前台运行对应进程，由 systemd 独立重启；容器中使用现有容器平台监督这些前台命令。

## 路由行为

- `/vlm/v1/chat/completions` 映射到 VLM `/v1/chat/completions`，保留 JSON、SSE 和错误状态。
- `/vlm/v1/models` 映射到 `/v1/models`。
- `/rag/v1/embeddings`、`/rag/v1/models` 映射到 RAG 的同名 `/v1` 接口，`/rag/health/ready` 映射到 `/health`。
- RAG 只公开 dense embedding；`/rag/v1/rerank` 保持 404。RAG 拥有独立上游 key 和并发额度。
- `/asr/v1/realtime` 使用 WebSocket Upgrade 转发到 ASR `/realtime`；`/asr/health/ready` 映射到 `/health`。
- ASR 路由关闭代理缓冲，空闲读取超时 3600 秒，最多 4 个活跃长连接；不公开文件转写路径。
- `/tts/v1/realtime` 使用 WebSocket Upgrade 转发到 TTS `/realtime`，并用 TTS 内部 key 覆盖公开 key。
- TTS 路由关闭代理缓冲，单消息上限由服务执行，最多 1 个活跃长连接，上游读写空闲超时
  3600 秒；不公开 TTS 健康、metrics、模型管理或音色管理路径。
- `/monitor/v1/overview` 返回每 5 秒更新的快照；`refresh=true` 等待立即采样，入口最多 8 个并发请求。内部算法 metrics 路径仍不公开。
- `/detector.v1.Detector/Detect` 保留 gRPC 消息、状态尾部、帧级错误和双向流。
- 其余算法路径返回 404，管理和 metrics 接口不被通配转发。
- HTTP 入口无/错 key 返回 401；gRPC 客户端得到 `UNAUTHENTICATED`。
- SSE 响应缓冲与缓存关闭，上游即使要求缓冲也不会启用；已取消的下游连接会关闭上游连接。
- 不自动重试模型请求。VLM 入口并发上限默认 4，超过返回 429；YOLO 最大活跃流默认 16，
  超过返回 gRPC `RESOURCE_EXHAUSTED`。额度按算法区分，不依赖调用方 IP。
- VLM 请求体上限默认 24 MiB，涵盖当前两张各 8 MiB 图片的 Base64 开销。
- RAG 请求体上限 256 KiB，入口活跃请求最多 4 个，上游空闲读取时限 60 秒；GPU 批量另由引擎控制。
  YOLO 长流不限制整条流的累计大小，每帧/消息仍由现有 YOLO 契约执行 4 MiB/8 MiB 限制。
- VLM 上游空闲读取时限默认 180 秒，YOLO 默认 120 秒；持续有数据的长流不会因总时长超过它而结束。
  CPU 的 gRPC deadline 仍控制整条 RPC。CPU 断开与计算终止之间的时间由引擎决定。
- 入口生成 `X-Request-ID`，覆盖调用方同名字段并传给上游；访问日志记录请求 ID、方法、路径、状态和耗时，
  不记录 Authorization、请求正文或查询参数。现有算法日志尚未全面接入这个请求 ID。

同一张 GPU 上的算力调度不由 NGINX 负责；入口并发限制不能当作多模型显存隔离。

## CPU 客户端

五个算法和监控的 `cpu_client/` 都有 `config.gateway.example.json`。将 `GPU_HOST` 替换成实际 GPU 地址，
将服务器证书放到配置文件旁，设置同一个 `GPU_API_KEY`。`ca_file` 相对配置文件解析，
`GPU_CA_FILE` 可覆盖它，建议使用绝对路径。使用系统信任的证书时可删除 `ca_file` 配置。
VLM 的旧 `VLM_API_KEY`、YOLO 的旧 `DETECTOR_AUTH_TOKEN` 仍作为未设置 `GPU_API_KEY` 时的兼容项。

VLM 示例：`python demo.py --config config.gateway.example.json --stream --prompt '请介绍一下自己'`。
YOLO 示例：`python demo.py --config config.gateway.example.json`，先修改其中的图片路径。
RAG 示例：在 `rag_service/cpu_client/` 运行 `python demo.py --config config.gateway.example.json --text '示例文档片段'`。
ASR 客户端用法见 `asr_service/cpu_client/README.md`；业务侧发送实时 PCM16 帧并并行读取识别事件。
TTS 示例：在 `tts_300m_service/cpu_client/` 运行
`python demo.py --config config.gateway.example.json --output output.wav < sentences.txt`。
监控示例：在 `monitor_service/cpu_client/` 运行 `python demo.py --config config.json`；手动刷新增加 `--refresh`。
CPU Web 后端负责向浏览器流式转发；在 CPU 一侧还有 NGINX 时，其流式路由也要关闭响应缓冲。

## 验收

网关测试使用真实 NGINX、TLS、HTTP/SSE 和 gRPC 上游测试桩；不加载模型。可复用 YOLO 本地环境及其
已安装的 grpc/protobuf，通过 SDK 验证 VLM：

```bash
source yolov5v70-service/scripts/corex_env.sh
python -m unittest discover -s gateway/tests -p test_gateway.py -v
```

该环境需要已有 OpenAI SDK 2.21.0 / HTTPX 0.28.1；本机从厂商环境复用。纯 CPU 测试环境可安装
YOLO `shared/` 和 VLM `cpu_client/requirements.txt`。
真实模型与故障隔离验收命令、结果见 `docs/validation.md`。

协议依据：[NGINX gRPC 与 HTTPS](https://nginx.org/en/docs/http/ngx_http_grpc_module.html)、
[响应缓冲](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_buffering)、
[并发连接限制](https://nginx.org/en/docs/http/ngx_http_limit_conn_module.html)。
