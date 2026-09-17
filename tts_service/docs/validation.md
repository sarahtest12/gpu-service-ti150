# Fun-CosyVoice3-0.5B-2512 部署验收

日期：2026-09-17。目标主机为双 BI-V150 32 GiB，CoreX 驱动 4.4.0；TTS 固定使用 GPU 0。
服务采用官方 CosyVoice3 原生 PyTorch FP16 路径，关闭 vLLM、TensorRT 和 JIT，固定
AISHELL-3 Apache-2.0 女声 `aishell3-female`。

## 固定资源

- 模型：`FunAudioLLM/Fun-CosyVoice3-0.5B-2512`，revision
  `29e01c4e8d000f4bcd70751be16fa94bf3d85a18`。权重、ONNX、模型配置和 tokenizer 共 13 个
  运行所需文件的 SHA-256 由 `config/server.json` 固定并经 `service.py check` 复验。
- 源码：`QwenAudio/CosyVoice` revision
  `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc`。四个运行时源码文件的补丁后 SHA-256
  由配置固定；补丁已在该 revision 的干净 worktree 上通过 `git apply --check`。启动时还会核对
  Git HEAD、整个工作树的允许差异摘要，以及 Matcha-TTS 子模块 revision 和清洁状态。
- 音色：AISHELL-3 SSB0005 女声派生参考音频，24000 Hz、单声道、187023 samples，
  SHA-256 `61c805554489cac6a89438f2551a6e53ab71bf9205d4b7d0a70fd738c02441b1`。
- 关键运行时：torch/torchaudio `2.7.1+corex.4.4.0`、ONNX Runtime `1.17.3`、
  transformers `4.51.3`、x-transformers `2.11.24`、pyworld `0.3.4`。
- 服务自带 Python 包由两个 requirements lock 文件固定版本及安装包 SHA-256；每次 bootstrap
  都从空虚拟环境重建，并拒绝锁文件之外的残留包。92 个来自 BI150 CoreX/系统镜像、且属于实际
  模型加载闭包的传递依赖由 `config/corex-packages.json` 固定版本、安装根和 RECORD SHA-256；
  启动时还按 RECORD 逐个复验源码和二进制文件，模型加载后核对实际导入包集合。已在新建的
  Python 3.10 `--system-site-packages` 虚拟环境中以 `--require-hashes --no-deps` 完整安装，并
  成功导入 CosyVoice3、CoreX torch、CPU ONNX Runtime 和 pyworld。
- 固定音色实测时长 7.792625 秒，峰值 12078，首尾静音各 0.2 秒，边缘噪声分别为
  -56.110 dBFS 与 -50.925 dBFS。启动门禁要求 PCM S16LE、24 kHz、单声道、5–10 秒、无削波、
  首尾静音各 0.05–0.5 秒、边缘噪声不高于 -45 dBFS且内部估算信噪比不低于 25 dB。音色清单
  自身由配置中的 SHA-256 固定；bootstrap 还会下载固定 revision 的 AISHELL-3 转写索引并逐字核对。

流式 generator 按官方实现直接进入 tokenizer，并明确跳过文本规范化前端。WeText/Pynini 仍以
哈希锁定，供非 generator 的固定参考文本规范化使用。运行时补丁删除了官方 `AutoModel` 的
ModelScope 自动下载分支；服务只接受配置中已经按 revision 和 SHA-256 准备好的本地模型目录。

## CoreX 兼容补丁

`patches/corex-runtime.patch` 包含四项部署修改：

1. speech tokenizer ONNX 固定使用 CPU provider，避免加载本机没有的 CUDA ONNX provider。
2. HiFi-GAN 的 f0 predictor 保留 float64 精度并移到 CPU。原实现的 GPU float64 Conv1d 在
   CoreX IXDNN 返回 `IXDNN_STATUS_BAD_PARAM`；其余 flow、LLM 与声码器仍在 GPU 运行。
3. 流式 hop 增长改为每个 utterance 的局部变量。原实现会把 25 写回并增长到 100，导致同一
   长连接的后续 utterance 必须等待更多 token；修复后每条 utterance 都从 25 开始。
4. 禁用 `AutoModel` 的模型名自动下载，只允许使用部署配置固定的现有本地目录。

## 模型级验证

执行：

```bash
tts_service/.venv/bin/python tts_service/scripts/validate_bistream.py \
  --config tts_service/config/server.json \
  --output tts_service/runtime/validation-bistream.pcm \
  --chunk-delay-seconds 0.1 \
  --finish-delay-seconds 15
```

结果为 `status=pass`。脚本先完成一条完整文本，再在同一模型实例上输入三段连贯中文；三段间隔
100 ms，最后一段后保持 generator 打开 15 秒才调用 `finish()`。第二条请求的首个 PCM 在
1.800244 秒产生，文本流在 15.206672 秒结束，严格满足首个 PCM 早于文本输入结束。

| 项目 | 完整文本 | 三段双流文本 |
| --- | ---: | ---: |
| 首个 PCM | 4.093432 s | 1.800244 s |
| 总耗时 | 13.888887 s | 31.937108 s |
| 音频时长 | 12.600000 s | 18.320000 s |
| PCM 字节 | 604800 | 879360 |
| 总体 RTF | 1.102293 | 1.743292 |

双流输出为 24 kHz、单声道、PCM S16LE，SHA-256
`fa2257ff92057ce93d06c306686e3a7714bfb06b234358c584431b75caf9db1d`。模型加载耗时
39.538271 秒；加载后进程显存 3848 MiB，torch allocated 3443.610 MB、reserved
3651.142 MB。两次推理后的进程显存仍为 3848 MiB，峰值 allocated 5628.889 MB。

## 复现与检查

```bash
bash tts_service/scripts/bootstrap.sh
tts_service/.venv/bin/python tts_service/scripts/service.py check
TTS_VENV_SITE="$PWD/tts_service/.venv/lib/python3.10/site-packages"
PYTHONPATH="$TTS_VENV_SITE:/usr/local/corex/lib64/python3/dist-packages" \
  tts_service/.venv/bin/python -m unittest discover -s tts_service/tests -p 'test_*.py' -v
```

## 运行服务与公共入口

旧 TTS 进程停止后，新服务在 `127.0.0.1:8004` 加载并通过内部鉴权 `/health`；进程显存为
3848 MiB。NGINX 只在内部健康通过后重载，随后公共入口与所有其他算法、监控进程都保持
`managed: true`、`ready: true`。

真实 CPU 客户端通过一个 `wss://localhost:8443/tts/v1/realtime` 连接顺序完成三条 utterance。
第一条发送三个 100 ms 间隔的文本块后保持输入打开，1.829533 秒收到首个 PCM，此后才发送
`input.done`；所以双向流式通过了 TTS、NGINX、TLS 和客户端整条链路。第二、三条继续复用同一
连接，首个 PCM 分别为 1.518033 秒、1.531372 秒。三条输出如下：

| utterance | PCM 字节 | 音频时长 | 总耗时 | SHA-256 |
| --- | ---: | ---: | ---: | --- |
| 1 | 869760 | 18.120000 s | 19.530475 s | `bcb78c973e7c1133e2634724e2a8c9f1c0f780416c10200c6027c022816b1330` |
| 2 | 541440 | 11.280000 s | 10.818417 s | `1b429c3f5fd2f6e1a84f56e5cf12cbd54a44f6d622f604b1668523ce72d71802` |
| 3 | 600960 | 12.520000 s | 12.901734 s | `ead95293172bcccd9f67b71eec585cb249cb15e60940851bcdc45dcae1e905b6` |

已删除的 `/tts/v1/audio/speech`、`/tts/v1/audio/voices`、`/tts/health/ready` 经统一公开 key
访问均为 404。`/monitor/v1/overview?refresh=true` 的最新快照中 TTS 为 `running`，显存
4034.920 MB（3848 MiB 换算为十进制 MB），近 60 秒 `time_to_first_token` 平均
124.039 ms、P95 296 ms。该指标止于首个语音 token，不包括 flow、声码器和网络首 PCM 时间。

切换前后验证结果为：TTS 29 项通过；网关协议 15 项通过；监控 6 项通过；另行启用运行中模型
开关后，YOLO、VLM、ASR 和统一健康/鉴权 4 项真实网关集成测试全部通过。NGINX 配置检查、
`service.py check` 与 `git diff --check` 均通过。最终公共长连接复验仍在一个连接内完成三条
utterance，首个 PCM 分别为 1.724061 秒、1.539448 秒和 1.529806 秒，第一条依旧先收到 PCM
再发送 `input.done`。

## 独立审查后的加固复验

独立审查后补齐了客户端取消与重连隔离、服务端收发同时完成时的状态竞争、PCM 及控制帧发送超时、
`generation_config.json` 哈希、固定音色官方转写与环境噪声门禁，以及 Python 环境复现检查。
CosyVoice 运行时不再导入 ModelScope 或按模型名自动下载；bootstrap 从空虚拟环境安装 36 个
哈希锁定的服务包，启动时再校验 92 个 CoreX/系统继承包的 RECORD 和实际文件内容，并验证主仓
HEAD、完整允许差异及 Matcha-TTS 子模块 revision。固定音色清单自身也由配置哈希固定。

最终 TTS 测试 50 项通过；网关测试 15 项通过（4 项需显式开启的真机集成测试跳过），监控测试
6 项通过，OpenAPI 3.1.1 校验通过。NGINX 配置、`service.py check`、干净官方 revision 上的
`git apply --check` 和 `git diff --check` 均通过。最终 HEAD 对应进程 PID 2189302 已就绪，
TTS 显存 4034.920 MB；YOLO、VLM、RAG、ASR、TTS、监控和网关均为 `managed: true`、
`ready: true`。完整基础包文件校验约耗时 47 秒，只在服务启动门禁执行。

重启后的第一次公共 WSS 请求包含模型热身：输入在 8.005937 秒结束，首 PCM 在 10.792735 秒
到达，因此该次只记录为冷启动数据，不作为双流通过证据；同一连接的下一条首 PCM 为
1.550774 秒。热身后再次保持输入开放 15 秒，首 PCM 在 1.640963 秒到达，`input.done` 在
15.002580 秒发送，严格双向流式成立。最终输出 1194240 字节 PCM，总耗时 40.408167 秒，
SHA-256 为 `20ea74f58ef0ef7ff9ff5928b97451915dbcdfbc662aa6518eee18935be6f7d9`。
验证文本未出现在 TTS 或网关日志中。

最终复审修复后再次经过统一 WSS 入口验证：重启后的首次请求保持输入开放 15 秒，首 PCM 在
4.220861 秒到达，`input.done` 在 15.003872 秒发送；最终得到 925440 字节 PCM，总耗时
33.320473 秒，SHA-256 为
`138119d058928cc27b36bca6145bd78dc9f3f2c7f499b74e8555939d3f21c25f`。近 60 秒 TTS TTFT
平均 888.947 ms、P95 1248 ms，验证文本仍未写入 TTS 或网关日志。

最终 HEAD 重启后的公共入口连通性复验首 PCM 为 4.346897 秒，输出 328320 字节 PCM，总耗时
7.524652 秒；服务完成后仍为 `ready: true`。
