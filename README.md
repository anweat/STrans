# STrans

智慧交通沙盘数字孪生实训项目资料与测试脚本。

当前阶段聚焦 ESP32-CAM 单摄像头接入：

- ESP32-CAM 组网与 CameraWebServer 测试；
- 浏览器访问 MJPEG 视频流；
- Python/OpenCV 拉取实时视频流并统计分辨率、帧率和截图；
- 为后续 ArUco 标定、沙盘坐标映射和数字孪生展示做准备。

当前 ESP32-CAM 烧录受限于硬件下载模式，详见：

```text
ESP32-CAM烧录阻塞与替代测试记录.md
```

## 目录

```text
智能交通沙盘数字孪生项目方案.md
ESP32-CAM阶段测试方案.md
esp32_cam_test/
  requirements.txt
  stream_test.py
  camera_source_test.py
  probe_esp32_cam.ps1
```

## 快速测试

### 前后端视频接入测试

启动后端：

```powershell
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动前端：

```powershell
cd frontend
pnpm install
pnpm dev
```

浏览器访问：

```text
http://localhost:5173
```

在页面右侧输入手机 IP 摄像头 App 提供的视频流地址，例如：

```text
http://手机IP:8080/video
rtsp://手机IP:8554/live
```

也可以输入 `0` 测试电脑自带摄像头。

### ESP32-CAM 测试

安装 Python 依赖：

```powershell
cd D:\codeproject\STrans\esp32_cam_test
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

探测串口和局域网候选地址：

```powershell
.\probe_esp32_cam.ps1 -Port COM3
```

编译并烧录 ESP32-CAM AP 模式固件：

```powershell
.\compile_upload_camera_ap.ps1 -Port COM3
```

烧录后 ESP32-CAM 会创建热点：

```text
SSID: STrans-ESP32CAM
Password: 12345678
Camera page: http://192.168.4.1
Stream URL: http://192.168.4.1:81/stream
```

拉取 ESP32-CAM 视频流：

```powershell
python .\stream_test.py --url http://ESP32_CAM_IP:81/stream --seconds 10 --out esp32_cam_snapshot.jpg
```

如果暂时无法烧录 ESP32-CAM，可先用 USB 摄像头或手机 IP 摄像头推进视觉链路：

```powershell
python .\camera_source_test.py --source 0 --seconds 10 --out usb_camera_snapshot.jpg
```

## 参考资料

- Espressif Arduino ESP32 官方仓库 CameraWebServer 示例：<https://github.com/espressif/arduino-esp32/blob/master/libraries/ESP32/examples/Camera/CameraWebServer/CameraWebServer.ino>
- Espressif ESP32 Camera Driver：<https://github.com/espressif/esp32-camera>
- ESP32-CAM 智慧交通违章检测参考项目：<https://github.com/gremlinflat/ESP32-CAM---Smart-Traffic-Violation-System>

## 手机摄像头云端转发

Ubuntu 云服务器上的 MediaMTX 转发、鉴权、手机推流和项目接入说明见：

```text
deploy/mediamtx/README.md
```
