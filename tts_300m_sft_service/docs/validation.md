# CosyVoice-300M-SFT 验证记录

## 2026-09-18 部署基线

官方 `iic/CosyVoice-300M-SFT` checkpoint 下载到
`/share/fshare/common/models/CosyVoice/CosyVoice-300M-SFT`。模型目录为 5.4 GB，配置采样率为
22050 Hz，包含 `中文女`、`中文男`、`粤语女`、`日语男`、`英文女`、`英文男` 和 `韩语女`
七个预置音色。本服务只开放 `中文女`。

服务使用独立目录、虚拟环境和内部 key，调用厂商 `inference_sft(..., stream=True)`。不接收或
注入 instruction；每个外部分段使用随机种子 42。公开协议继续使用 `input.segment` FIFO、
PCM S16LE、活动分段取消和同一 WebSocket 多段复用。

网关 `tts.project` 默认选择 `tts_300m_sft_service`。CosyVoice-300M-Instruct 和 CosyVoice3
服务继续保留，三个服务都监听 `127.0.0.1:8004`，因此同一时间只能运行一个。

## 真机部署与公开入口验收

`bootstrap.sh` 从 hash lock 创建独立 `.venv`；`service.py check` 已通过 CoreX/CUDA、CosyVoice
导入、固定源码哈希、checkpoint 哈希和 JIT 制品检查。服务启动后，网关管理器确认运行解释器、
工作目录、配置和内部 key 均来自 `tts_300m_sft_service`。监控进程和网关随后重启/重载，避免沿用
上一套 TTS 的内部 key。

| 项目 | 结果 |
| --- | --- |
| SFT 服务、协议与 CPU 客户端测试 | 54 项通过 |
| 300M-Instruct / Fun-CosyVoice3 回归 | 各 54 项通过 |
| 网关测试 | 共 22 项：18 项通过，4 项显式真机集成测试跳过 |
| 监控测试 / OpenAPI 3.1.1 | 6 项通过 / 通过 |
| `service.py check` / `git diff --check` | 通过 / 通过 |
| 最新公开短句 | 106496 字节、22050 Hz、单声道 PCM S16LE |
| 最新监控快照 | `running`，2254.438 MB，首 token avg 26.742 ms / P95 39 ms |

真实 CPU 客户端通过统一 TLS/WSS 入口连接后，`session.created` 返回
`cosyvoice-300m-sft`、`中文女` 和 22050 Hz PCM。两段数字文本按 FIFO 完成：冷启动段
“今天是2026年9月18日。”首 PCM 为 19.532 秒、总耗时 21.105 秒、119808 字节；排队的
“温度23.5度，完成率12%。”总耗时 29.930 秒、117760 字节。将结果交给本机 ASR 复核，日期
内容正确，第二段得到“温度二十三点五度，完成率百分之十二。”，验证了中文数字规范化。

热身后，同一短句连续两次合成的首 PCM 分别为 5.701 秒和 7.897 秒；第二个请求包含 FIFO
排队时间。两次 PCM 哈希不同，SFT 推理并非逐字节确定。对同一较长句子的两次输出使用 checkpoint
自带 CAMPPlus 提取 speaker embedding，音频时长分别为 5.433 秒和 6.304 秒，余弦相似度为
0.932209。该结果支持固定 `中文女` 的部署选择，但不构成跨任意文本听感完全一致的保证。

活动段取消在已经收到 77824 字节后发出；服务排空不可抢占的厂商 generator，9.013 秒后返回
`response.cancelled`，没有把等待段启动为新音频，连接状态保持可用。取消延迟取决于当时已经进入
GPU 的计算量。

最新公开监控快照中五个算法均为 `running`。TTS 60 秒窗口在无请求时会按契约返回
`avg_ms: null`、`p95_ms: null`；发送一条短句后立即强制刷新，TTS 显存为 2254.438 MB，GPU
首 speech token 平均 26.742 ms、P95 39 ms。该指标不含 FIFO 排队、flow/声码器和网络首 PCM
时间，因此不能与客户端首 PCM 直接比较。日志未发现请求文本、instruction、`ERROR` 或
`Traceback`。以上延迟只描述该次 BI150 验收，不是服务等级承诺。
