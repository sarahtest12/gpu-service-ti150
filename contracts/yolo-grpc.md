# YOLO gRPC 契约 Review

唯一正式源为 [`detector.proto`](../yolov5v70-service/shared/detector_contract/detector.proto)。
本文件解释现有约束，不复制或修改 proto。原生双向流不通过 OpenAPI 伪装为 HTTP JSON 请求。

```proto
package detector.v1;
service Detector {
  rpc Detect(stream DetectionFrame) returns (stream DetectionResult);
}
```

## 连接与调用

- 对外目标 `GPU_HOST:8443`，TLS，HTTP/2。
- 方法路径 `/detector.v1.Detector/Detect`，与 VLM 共用目标端口。
- metadata 为 `authorization: Bearer <GPU_API_KEY>`；网关注入独立 YOLO 内部 key。
- 一条 RPC 持续发送帧并接收结果，无需等待发送完全部帧再接收；不要每帧重连。
- 单条流按请求顺序返回。不同流可并发；网关默认最多 16 条活跃流。
- CPU deadline 控制整条 RPC；网关上游空闲读写时限为 120 秒，持续有数据的长流不以总时长截断。
- CPU 取消或关闭连接会关闭上游流；已经进入 GPU 的计算不承诺立即中断。

## 输入 DetectionFrame

| 字段 | protobuf 类型 | 约束 / 含义 |
| --- | --- | --- |
| `stream_id` | string | 1–128 字符，不能包含 ASCII 控制字符；通常标识摄像头 |
| `frame_id` | uint64 | 大于 0；CPU 负责同一路的单调递增，服务端未维护跨请求序号状态 |
| `observed_at_unix_ms` | int64 | CPU 采集时间，Unix 毫秒；0 表示未提供，不做到达帧龄检查 |
| `width` / `height` | uint32 | 真实 JPEG 尺寸，范围 1–16384，须与解码结果一致 |
| `jpeg` | bytes | 非空 JPEG，默认最大 4194304 字节（4 MiB）；原生消息中不是 Base64 字符串 |
| `source_pts` | int64 | 视频源 PTS，服务端原样传回 |
| `time_base_num` / `time_base_den` | uint32 | PTS 时间基；同时为 0，或同时为正数 |

单条 protobuf 消息默认最大 8388608 字节（8 MiB）。整条长流没有累计请求体大小上限。
默认超过 1000 ms 的到达帧龄返回 `EXPIRED`；CPU/GPU 需同步时钟。
默认排队超过 250 ms 的帧也可能返回 `EXPIRED`，队列容量默认为 8。
这些是当前部署默认值，以服务配置与共享 `TransportConfig` 为准。

## 输出 DetectionResult

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `stream_id` / `frame_id` | string / uint64 | 对应输入标识 |
| `observed_at_unix_ms` | int64 | 原始采集时间 |
| `completed_at_unix_ms` | int64 | GPU 服务生成结果的 Unix 毫秒时间 |
| `detections` | repeated BoundingBox | 检测框；成功但没有目标时可以为空 |
| `preprocess_ms` | float | 预处理耗时，毫秒 |
| `inference_ms` | float | 模型推理耗时，毫秒；监控要求使用这一阶段 |
| `nms_ms` | float | NMS 耗时，毫秒 |
| `code` | ResultCode | 帧级结果，见下表 |
| `error_message` | string | 帧级错误说明，最多 512 字符；不作为稳定错误分类依据 |
| `source_pts` / `time_base_num` / `time_base_den` | int64 / uint32 / uint32 | 原样返回输入时间线信息 |

`BoundingBox` 的 `x1/y1/x2/y2` 是相对原图的 `[0,1]` 归一化 xyxy；
其他字段为 `class_id: uint32`、`label: string`、`confidence: float`。

当前批量为 1，`inference_ms` 对应单帧模型调用。
若后续开启微批，现有实现将批次阶段耗时放入各帧结果，不能直接宣称为独立测得的单帧耗时；
监控“每帧推理耗时”口径需随批量策略重新核对。

## 错误语义

| ResultCode 数值 / 名称 | 含义 | 是否关闭流 |
| --- | --- | --- |
| 0 / `UNSPECIFIED` | 未指定；客户端不应视为成功 | 非成功处理 |
| 1 / `OK` | 检测成功，可以没有检测框 | 否 |
| 2 / `INVALID_FRAME` | 请求字段、JPEG 或尺寸无效 | 否 |
| 3 / `OVERLOADED` | 推理队列过载 | 否 |
| 4 / `INFERENCE_ERROR` | 推理失败或服务正在关闭 | 否 |
| 5 / `EXPIRED` | 到达帧龄或排队超时 | 否 |

完整枚举名带 `RESULT_CODE_` 前缀。帧级失败后，同一流可以继续发送下一帧。
错误结果中的阶段耗时属于 proto3 默认值，不能把默认 0 当作真实完成的推理样本。

连接/RPC 级错误另由 gRPC 状态表达，例如：

- `UNAUTHENTICATED`（16）：缺失或错误的公开 key。
- `RESOURCE_EXHAUSTED`（8）：网关活跃流额度超过 16，或超过 gRPC 消息大小限制。
- `UNAVAILABLE`（14）：YOLO 上游未启动、连接失败等。
- `DEADLINE_EXCEEDED`（4）：客户端整条 RPC deadline 到期。
- `CANCELLED`（1）：客户端取消。

调试时使用 protobuf JSON 映射会把 uint64/int64 表示为字符串、bytes 表示为 Base64；
这是调试表示法，不是另一套 HTTP 接口。CPU 与 GPU 应使用同版本 `shared/` 生成绑定。
