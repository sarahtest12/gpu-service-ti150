# Fun-CosyVoice3-0.5B-2512 部署验收

日期：2026-09-17。目标主机为双 BI-V150 32 GiB；TTS 使用 GPU 0，VLM 使用 GPU 1。TTS 采用
官方 CosyVoice3 原生 PyTorch FP16 路径，关闭 vLLM、TensorRT 和 JIT，固定 AISHELL-3
Apache-2.0 女声 `aishell3-female`。

## 配置、资源与协议检查

| 验证 | 结果 |
| --- | --- |
| 模型 revision 与 6 个大文件 SHA-256 | 通过 |
| 官方 CosyVoice 源码 revision、Matcha 子模块与 3 个关键源码 SHA-256 | 通过 |
| AISHELL-3 原文件、裁剪范围和派生 24 kHz WAV SHA-256 | 通过 |
| CoreX torch/torchaudio 与固定前端依赖版本 | 通过 |
| CPU ONNX Runtime 可用且没有 CUDA provider | 通过 |
| TTS 引擎、WebSocket 状态机、服务配置与 CPU 客户端单元测试 | 24 项通过 |
| 真实 NGINX/TLS TTS WebSocket、内部 key 替换、单连接限制和旧路径 404 | 通过 |
| NGINX 全量协议测试 | 15 项通过；4 项运行中模型验收按开关跳过 |

`service.py check` 已完成模型、源码、音色、包版本和导入检查。固定模型目录为
`/share/fshare/common/models/CosyVoice/Fun-CosyVoice3-0.5B-2512`，源码 revision 为
`074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc`，模型 revision 为
`29e01c4e8d000f4bcd70751be16fa94bf3d85a18`。音色派生 WAV 为 24000 Hz、单声道、
187023 samples，SHA-256 为
`61c805554489cac6a89438f2551a6e53ab71bf9205d4b7d0a70fd738c02441b1`。

## 待记录的真实模型数据

下一阶段在 CoreX 上执行完整文本与延迟三段文本 generator，验证首个 PCM 是否早于 generator
完成，并记录模型加载显存、稳定显存、生成峰值、首语音 token、首 PCM、总耗时和 RTF。随后通过
内部 WebSocket 连续合成三条 utterance，再经统一 WSS 入口复验固定音色、连接复用和监控快照。
只有这些检查通过后才切换运行中的公开 TTS 服务。

## 复现

```bash
bash tts_service/scripts/bootstrap.sh
tts_service/.venv/bin/python tts_service/scripts/service.py check
TTS_VENV_SITE="$PWD/tts_service/.venv/lib/python3.10/site-packages"
PYTHONPATH="$TTS_VENV_SITE:/usr/local/corex/lib64/python3/dist-packages" \
  tts_service/.venv/bin/python -m unittest discover -s tts_service/tests -p 'test_*.py' -v
source yolov5v70-service/scripts/corex_env.sh
python -m unittest discover -s gateway/tests -p 'test_*.py' -v
```
