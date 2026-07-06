# STrans

云边端协同智慧交通视觉感知与沙盘数字孪生实训项目资料、需求设计文档和阶段测试脚本。

项目面向学院 704 智慧交通沙盘，目标是用手机或 ESP32-CAM 作为边缘采集设备，电脑作为边/云端分析节点，前端大屏展示车辆识别、车牌/电子 ID 白名单通行决策、拥堵热力图、禁停告警、道路异常和历史统计。

当前阶段聚焦“稳定演示闭环”：

- 手机或 ESP32-CAM 单摄像头接入；
- Python/OpenCV 拉取实时视频流并统计分辨率、帧率和截图；
- 车辆、车牌/电子 ID、障碍物和道路区域事件识别方案设计；
- 设备管理、模型管理、系统资源监控、白名单通行决策和历史统计设计；
- 为后续 ArUco 标定、沙盘坐标映射、Mock 交通流和数字孪生展示做准备。

当前 ESP32-CAM 烧录受限于硬件下载模式，详见：

```text
ESP32-CAM烧录阻塞与替代测试记录.md
```

## 目录

```text
智能交通沙盘数字孪生项目方案.md
需求分析文档_V1.0.md
系统设计文档_V1.0.md
算法方案详细设计.md
ESP32-CAM阶段测试方案.md
esp32_cam_test/
  requirements.txt
  stream_test.py
  camera_source_test.py
  probe_esp32_cam.ps1
```

## 快速测试

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
