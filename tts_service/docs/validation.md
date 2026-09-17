# Fun-CosyVoice3-0.5B-2512 部署验收

日期：2026-09-17。目标主机为双 BI-V150 32 GiB，CoreX 驱动 4.4.0；TTS 固定使用 GPU 0。
服务采用官方 CosyVoice3 原生 PyTorch FP16 路径，关闭 vLLM、TensorRT 和 JIT，固定
AISHELL-3 Apache-2.0 女声 `aishell3-female`。

## 固定资源

- 模型：`FunAudioLLM/Fun-CosyVoice3-0.5B-2512`，revision
  `29e01c4e8d000f4bcd70751be16fa94bf3d85a18`。六个大文件 SHA-256 由
  `config/server.json` 固定并经 `service.py check` 复验。
- 源码：`QwenAudio/CosyVoice` revision
  `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc`。四个运行时源码文件的补丁后 SHA-256
  由配置固定；补丁已在该 revision 的干净 worktree 上通过 `git apply --check`。
- 音色：AISHELL-3 SSB0005 女声派生参考音频，24000 Hz、单声道、187023 samples，
  SHA-256 `61c805554489cac6a89438f2551a6e53ab71bf9205d4b7d0a70fd738c02441b1`。
- 关键运行时：torch/torchaudio `2.7.1+corex.4.4.0`、ONNX Runtime `1.17.3`、
  transformers `4.51.3`、x-transformers `2.11.24`、pyworld `0.3.4`。

流式 generator 按官方实现直接进入 tokenizer，并明确跳过文本规范化前端。因此部署不安装会在
启动时动态下载 FST 的 `wetext`；这避免离线服务启动时访问 ModelScope，不改变流式输入路径。

## CoreX 兼容补丁

`patches/corex-runtime.patch` 包含三项从真机错误定位得到的最小修改：

1. speech tokenizer ONNX 固定使用 CPU provider，避免加载本机没有的 CUDA ONNX provider。
2. HiFi-GAN 的 f0 predictor 保留 float64 精度并移到 CPU。原实现的 GPU float64 Conv1d 在
   CoreX IXDNN 返回 `IXDNN_STATUS_BAD_PARAM`；其余 flow、LLM 与声码器仍在 GPU 运行。
3. 流式 hop 增长改为每个 utterance 的局部变量。原实现会把 25 写回并增长到 100，导致同一
   长连接的后续 utterance 必须等待更多 token；修复后每条 utterance 都从 25 开始。

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

公开 WSS 长连接复用、旧 HTTP 路由移除、监控快照和运行中服务显存将在网关切换后记录到本文件及
`contracts/validation.md`、`gateway/docs/validation.md`。
