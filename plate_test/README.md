# 车牌识别测试工具

本目录用于快速验证 HyperLPR3 开源中文车牌识别模型在单张图片上的效果。

## 安装依赖

```powershell
python -m pip install -r plate_test\requirements.txt
```

首次导入 `hyperlpr3` 时会自动下载 ONNX 模型到用户目录下的 `.hyperlpr3` 文件夹。

## 单张图片测试

```powershell
python plate_test\recognize_plate.py --src path\to\car.jpg --out plate_test_output.jpg --json-out plate_test_result.json
```

也可以直接传图片 URL：

```powershell
python plate_test\recognize_plate.py --src https://example.com/car.jpg --out plate_test_output.jpg
```

如果车牌较小或画面较复杂，可以尝试高精度检测：

```powershell
python plate_test\recognize_plate.py --src path\to\car.jpg --det-level high
```

## 输出说明

脚本会输出 JSON：

- `plate_no`：识别出的车牌号；
- `confidence`：识别置信度；
- `plate_type`：车牌类型；
- `bbox`：车牌框 `[x1, y1, x2, y2]`；
- `elapsed_ms`：单张图片识别耗时。

同时会保存一张标注图，方便写测试报告或放到 PPT 里。
