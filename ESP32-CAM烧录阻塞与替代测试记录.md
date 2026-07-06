# ESP32-CAM 烧录阻塞与替代测试记录

## 1. 当前状态

本机已经完成以下准备：

- Arduino CLI 已安装并可用；
- ESP32 Arduino core 已安装：`esp32:esp32 3.3.10`；
- ESP32-CAM 板型已识别为可用目标：`esp32:esp32:esp32cam`；
- 本项目 AP 模式 CameraWebServer 固件已经编译通过；
- USB 串口曾识别为 `USB-SERIAL CH340 (COM3)`。

当前阻塞点在烧录阶段：

```text
A fatal error occurred: Failed to connect to ESP32: Wrong boot mode detected (0xb)!
The chip needs to be in download mode.
```

## 2. 阻塞原因判断

该错误说明电脑和 ESP32 串口之间有通信，`esptool` 能读到 ROM 启动日志，但 ESP32 没有进入固件下载模式。

根据 Espressif 官方 esptool 文档：

- ESP32 需要在复位时让 `GPIO0` 保持低电平，才会进入串口 bootloader；
- 如果 `GPIO0` 为高电平或悬空，ESP32 会进入普通 flash 启动模式；
- 对没有自动下载电路的板子，需要手动按住 `BOOT` / 拉低 `IO0`，再按 `EN` / `RST`；
- `Wrong boot mode detected` 通常指自动复位进入下载模式失败，需要检查自动下载电路或手动进入 download mode。

因此，本次不是代码编译问题，也不是 OpenCV 拉流问题，而是硬件下载模式问题。

## 3. 后续 ESP32-CAM 烧录建议

优先方案：

1. 使用可靠的 USB-TTL 烧录模块或 ESP32-CAM-MB 下载底板；
2. 确认供电为稳定 5V；
3. 烧录时连接：

| USB-TTL | ESP32-CAM |
|---|---|
| 5V | 5V |
| GND | GND |
| TX | U0R |
| RX | U0T |
| GND | IO0 |

4. 按 `RST` 后执行上传；
5. 上传完成后断开 `IO0-GND`，再次按 `RST` 正常启动。

如果使用带按键的下载底板：

1. 按住 `BOOT` / `IO0`；
2. 按一下 `RST` / `EN`；
3. 开始上传；
4. 出现连接成功或开始写入 flash 后可松开 `BOOT`；
5. 上传完成后按 `RST` 正常启动。

## 4. 替代测试路线

为了不影响智慧交通实训进度，建议先绕过 ESP32-CAM 烧录，继续推进视觉链路：

```text
USB 摄像头 / 手机 IP 摄像头
  -> OpenCV 拉流
  -> 保存截图、记录分辨率和 FPS
  -> ArUco 标定
  -> 图像坐标到沙盘坐标映射
  -> 后续替换为 ESP32-CAM 视频流
```

这样第一阶段的核心能力仍然可以交付：

- 摄像头实时视频接入；
- OpenCV 读取视频流；
- ArUco 标定；
- Homography 坐标映射；
- 沙盘视觉输入链路验证。

后续 ESP32-CAM 烧录成功后，只需要把视频源从 USB/手机 URL 替换为：

```text
http://192.168.4.1:81/stream
```

## 5. 通用摄像头测试命令

测试本机 USB 摄像头：

```powershell
cd D:\codeproject\STrans\esp32_cam_test
python .\camera_source_test.py --source 0 --seconds 10 --out usb_camera_snapshot.jpg
```

测试手机 IP 摄像头或后续 ESP32-CAM：

```powershell
python .\camera_source_test.py --source http://摄像头IP:端口/video --seconds 10 --out ip_camera_snapshot.jpg
python .\camera_source_test.py --source http://192.168.4.1:81/stream --seconds 10 --out esp32_cam_snapshot.jpg
```

## 6. 阶段结论模板

```text
本阶段已完成 ESP32-CAM 开发环境、Arduino CLI、ESP32 core 和测试固件准备，AP 模式 CameraWebServer 固件可正常编译。实际烧录阶段由于当前 ESP32-CAM 硬件未能进入下载模式，esptool 报告 Wrong boot mode detected，判断为 IO0/BOOT 下载模式或下载底板问题。为保证实训进度，先采用 USB 摄像头或手机 IP 摄像头完成 OpenCV 拉流、截图、帧率统计和后续 ArUco 标定流程；待 TTL/USB 下载模块到位后，再补充 ESP32-CAM 烧录和视频流实测结果。
```

## 7. 参考资料

- Espressif esptool ESP32 Boot Mode Selection：<https://docs.espressif.com/projects/esptool/en/latest/esp32/advanced-topics/boot-mode-selection.html>
- Espressif esptool ESP32 Troubleshooting：<https://docs.espressif.com/projects/esptool/en/latest/esp32/troubleshooting.html>
- Espressif esptool Entering the Bootloader：<https://docs.espressif.com/projects/esptool/en/latest/esp32/esptool/entering-bootloader.html>
