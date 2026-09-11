# CPU Web 后端监控客户端

安装 `requirements.txt`，复制 `config.gateway.example.json` 为 `config.json`，把 `GPU_HOST`
改为 CPU 服务器可访问的 GPU 地址，并把 GPU 网关证书放到配置文件旁。调用前通过环境变量设置
统一入口的 `GPU_API_KEY`。

```bash
python demo.py --config config.json
python demo.py --config config.json --refresh
```

普通调用读取 GPU 监控服务每 5 秒生成的最新快照，适合 CPU Web 后端的定时广播任务；
`--refresh` 会等待一次即时采样，供页面手动刷新使用。客户端不建立到 GPU 的长连接。
