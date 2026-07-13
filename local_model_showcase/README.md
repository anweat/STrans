# STrans 本地模型演示

独立演示目录：`Sandtable Auto YOLO + ByteTrack + HyperLPR3`。

## 一键启动

双击：

```bat
run_demo.bat
```

启动后浏览器会打开：

```text
http://127.0.0.1:9100
```

## 能展示什么

- 图片上传识别：车辆、行人、自行车等 VisDrone 类别。
- ByteTrack 跟踪：视频流模式会保留目标 ID。
- HyperLPR3 车牌识别：对车辆框裁剪后尝试识别中文车牌。
- 视频源演示：支持电脑摄像头、手机 IP Webcam、RTSP、本地视频文件路径。

## 模型选择建议

当前沙盘摄像头近景和模型车特征更接近通用 COCO 车辆类别，因此页面默认使用：

```text
沙盘推荐模式（YOLO11s 自动）
```

`YOLOv11s-VisDrone` 更适合无人机远景小目标，但在近距离沙盘车牌特写视角下容易漏掉整车。

## 视频流效果调参建议

实时视频流比单张图片更容易受压缩、运动模糊、遮挡和码率影响，因此页面默认对视频流使用更稳的参数：

```text
视频置信度：0.30
最小框面积：1200
只显示车辆相关目标：开启
```

当前版本使用沙盘增强策略：

```text
YOLO 低阈值车辆检测
ByteTrack 保持目标连续性
HyperLPR3 每 3 帧整帧扫车牌
车牌识别成功但 YOLO 漏车时，自动反推疑似车辆框
```

如果漏检明显，把最小框面积降到 `600`；如果误检明显，把视频置信度升到 `0.45`，或把最小框面积调到 `1800`。

## 常用视频源写法

```text
camera
http://手机IP:8080/video
rtsp://用户名:密码@摄像头IP:554/xxx
D:\path\to\test.mp4
```

## API

```text
GET  /health
POST /api/infer/image
POST /api/infer/base64
GET  /api/stream/mjpeg?source=camera
```

## 权重说明

`download_models.py` 会优先下载 Hugging Face 上的 `erbayat/yolov11s-visdrone` 权重到：

```text
weights\yolov11s-visdrone.pt
```

同时会下载官方 `yolo11s.pt` 作为备用权重。如果后续队友给你训练后的沙盘专用模型，把文件放到 `weights\yolov11s-visdrone.pt` 并覆盖即可。
