# BI-V150 VLM 服务

本目录是独立算法部署项目。任务范围为图片、文档理解和业务工具调用，不包含视频。

- 部署、启停或修改配置前读 `README.md`，配置的唯一来源为 `config/server.json`。
- 本机固定使用物理 GPU 1；GPU 0 的 YOLO 服务与环境保持独立。
- 使用 `scripts/bootstrap.sh` 建立本地环境，并通过 `scripts/service.py` 管理本项目进程。
- `.venv` 复用厂商镜像的 vLLM/CoreX 包；不在宿主 SDK 或 YOLO 环境中安装、升级依赖。
- `runtime/` 含私密令牌、PID 状态和日志，不进入 Git 或交付包。
- 客户端使用标准 HTTP `/v1/chat/completions`；业务工具在 CPU 应用校验和执行。
- 已确认的验收 seam 为真实 HTTP 接口的图片问答、文档字段抽取和工具调用闭环；命令见 README。
- 修改厂商包的版本或源码前先说明兼容性影响并取得授权；配置可调参数优先局限在本项目内。

本工作区存在父目录文档时，环境迁移和多算法规划还应阅读 `../docs/deployment-environment.md`
与 `../docs/development-handoff.md`；独立交付不依赖这些文件。
