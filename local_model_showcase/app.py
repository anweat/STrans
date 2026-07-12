from __future__ import annotations

import base64
import re
import time
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from ultralytics import YOLO


ROOT = Path(__file__).resolve().parent
WEIGHTS = ROOT / "weights"
OUTPUTS = ROOT / "outputs"
STATIC = ROOT / "static"
OUTPUTS.mkdir(exist_ok=True)

VISDRONE_MODEL = WEIGHTS / "yolov11s-visdrone.pt"
FALLBACK_MODEL = WEIGHTS / "yolo11s.pt"

VEHICLE_CLASS_NAMES = {
    "car",
    "van",
    "truck",
    "bus",
    "motorcycle",
    "motorbike",
    "motor",
    "tricycle",
    "awning-tricycle",
    "bicycle",
}

app = FastAPI(title="STrans Local Model Showcase", version="1.0.0")
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS)), name="outputs")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

PLATE_PATTERN = re.compile(r"^[\u4e00-\u9fa5][A-Z][A-Z0-9]{5,6}$")
models: dict[str, YOLO] = {}
active_model_path: Path | None = None
plate_catcher: Any | None = None
plate_error: str | None = None


def clamp_box(box: list[int], width: int, height: int) -> list[int]:
    x1, y1, x2, y2 = box
    return [
        max(0, min(width - 1, x1)),
        max(0, min(height - 1, y1)),
        max(0, min(width - 1, x2)),
        max(0, min(height - 1, y2)),
    ]


def box_iou(a: list[int], b: list[int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1, inter_y1 = max(ax1, bx1), max(ay1, by1)
    inter_x2, inter_y2 = min(ax2, bx2), min(ay2, by2)
    inter_area = max(0, inter_x2 - inter_x1) * max(0, inter_y2 - inter_y1)
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter_area
    return inter_area / union if union else 0.0


def plate_to_vehicle_box(plate_box: list[int], image_shape: tuple[int, int, int]) -> list[int]:
    height, width = image_shape[:2]
    x1, y1, x2, y2 = plate_box
    plate_w = max(1, x2 - x1)
    plate_h = max(1, y2 - y1)
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2

    vehicle_w = int(plate_w * 3.8)
    vehicle_h = int(plate_h * 5.2)
    # 沙盘车辆多为俯视/斜俯视，车牌通常靠近车头或车尾，候选框向上多扩一些。
    vx1 = cx - vehicle_w // 2
    vx2 = cx + vehicle_w // 2
    vy1 = cy - int(vehicle_h * 0.62)
    vy2 = cy + int(vehicle_h * 0.38)
    return clamp_box([vx1, vy1, vx2, vy2], width, height)


def resolve_model_path(model_name: str = "visdrone") -> Path:
    if model_name in {"auto", "fallback"}:
        candidate = FALLBACK_MODEL
    else:
        candidate = VISDRONE_MODEL if VISDRONE_MODEL.exists() else FALLBACK_MODEL
    if not candidate.exists():
        raise RuntimeError("No YOLO weights found. Run download_models.py first.")
    return candidate


def load_detector(model_name: str = "visdrone") -> YOLO:
    global active_model_path
    candidate = resolve_model_path(model_name)
    key = str(candidate.resolve())
    if key in models:
        active_model_path = candidate
        return models[key]

    detector = YOLO(str(candidate))
    models[key] = detector
    active_model_path = candidate
    return detector


def load_plate_catcher() -> Any | None:
    global plate_catcher, plate_error
    if plate_catcher is not None or plate_error is not None:
        return plate_catcher
    try:
        import hyperlpr3 as lpr3

        plate_catcher = lpr3.LicensePlateCatcher()
    except Exception as exc:
        plate_error = str(exc)
    return plate_catcher


def image_from_upload(file_bytes: bytes) -> np.ndarray:
    data = np.frombuffer(file_bytes, np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Invalid image file.")
    return image


def normalize_plate_result(raw: Any) -> list[dict[str, Any]]:
    plates: list[dict[str, Any]] = []
    if not raw:
        return plates
    for item in raw:
        text = ""
        confidence = 0.0
        bbox: list[int] | None = None
        plate_type = ""
        if isinstance(item, (list, tuple)):
            text = str(item[0]) if len(item) > 0 else ""
            confidence = float(item[1]) if len(item) > 1 and isinstance(item[1], (int, float)) else 0.0
            if len(item) > 2 and isinstance(item[2], (list, tuple)):
                bbox = [int(v) for v in item[2][:4]]
            elif len(item) > 2:
                plate_type = str(item[2])
            if len(item) > 3 and isinstance(item[3], (list, tuple)):
                bbox = [int(v) for v in item[3][:4]]
            elif len(item) > 3:
                plate_type = str(item[3])
        else:
            text = str(item)
        plates.append({"text": text, "confidence": confidence, "bbox": bbox, "type": plate_type})
    return plates


def detect_plates(image: np.ndarray, min_confidence: float = 0.0) -> list[dict[str, Any]]:
    catcher = load_plate_catcher()
    if catcher is None:
        return []
    try:
        plates = normalize_plate_result(catcher(image))
        return [
            plate
            for plate in plates
            if PLATE_PATTERN.match(str(plate.get("text", "")))
            and float(plate.get("confidence", 0.0)) >= min_confidence
        ]
    except Exception:
        return []


def is_vehicle_class(class_name: str) -> bool:
    normalized = class_name.lower().replace("_", "-")
    return normalized in VEHICLE_CLASS_NAMES


def draw_label(image: np.ndarray, box: list[int], label: str, color: tuple[int, int, int]) -> None:
    x1, y1, x2, y2 = box
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
    cv2.putText(
        image,
        label,
        (x1, max(20, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        color,
        2,
        cv2.LINE_AA,
    )


def infer_image(image: np.ndarray, conf: float = 0.25, imgsz: int = 960, model_name: str = "auto") -> dict[str, Any]:
    detector = load_detector(model_name)
    started = time.perf_counter()
    results = detector.track(
        source=image,
        conf=conf,
        imgsz=imgsz,
        tracker="bytetrack.yaml",
        persist=True,
        verbose=False,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    result = results[0]
    names = result.names
    annotated = image.copy()
    detections: list[dict[str, Any]] = []
    vehicle_boxes: list[list[int]] = []

    boxes = result.boxes
    if boxes is not None and len(boxes) > 0:
        xyxy = boxes.xyxy.cpu().numpy()
        classes = boxes.cls.cpu().numpy().astype(int)
        confs = boxes.conf.cpu().numpy()
        ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else [None] * len(xyxy)

        for idx, (box, cls_id, det_conf, track_id) in enumerate(zip(xyxy, classes, confs, ids)):
            x1, y1, x2, y2 = [int(v) for v in box]
            class_name = names.get(int(cls_id), str(cls_id))
            bbox = [x1, y1, x2, y2]
            crop = image[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
            plates = detect_plates(crop, min_confidence=0.0) if is_vehicle_class(class_name) and crop.size else []
            label = f"{class_name} {det_conf:.2f}"
            if track_id is not None:
                label = f"ID{track_id} {label}"
            if plates:
                label += f" {plates[0]['text']}"

            draw_label(annotated, bbox, label, (36, 107, 253))
            if is_vehicle_class(class_name):
                vehicle_boxes.append(bbox)
            detections.append(
                {
                    "track_id": None if track_id is None else int(track_id),
                    "class_id": int(cls_id),
                    "class_name": class_name,
                    "confidence": round(float(det_conf), 4),
                    "bbox": bbox,
                    "plates": plates,
                }
            )

    full_image_plates = detect_plates(image, min_confidence=0.0)
    for plate in full_image_plates:
        bbox = plate.get("bbox")
        if not bbox:
            continue
        x1, y1, x2, y2 = [int(v) for v in bbox]
        plate_box = [x1, y1, x2, y2]
        draw_label(annotated, plate_box, f"plate {plate['text']} {float(plate.get('confidence', 0.0)):.2f}", (20, 184, 166))
        if not any(box_iou(plate_box, vehicle_box) > 0.02 for vehicle_box in vehicle_boxes):
            derived_box = plate_to_vehicle_box(plate_box, image.shape)
            draw_label(annotated, derived_box, f"plate-derived vehicle {plate['text']}", (14, 165, 233))
            vehicle_boxes.append(derived_box)
            detections.append(
                {
                    "track_id": None,
                    "class_id": -1,
                    "class_name": "plate-derived vehicle",
                    "confidence": round(float(plate.get("confidence", 0.0)), 4),
                    "bbox": derived_box,
                    "plates": [plate],
                }
            )

    output_name = f"{uuid.uuid4().hex}.jpg"
    output_path = OUTPUTS / output_name
    cv2.imwrite(str(output_path), annotated)

    return {
        "model": str(active_model_path.name if active_model_path else ""),
        "tracker": "ByteTrack/bytetrack.yaml",
        "plate_model": "HyperLPR3" if plate_error is None else f"HyperLPR3 unavailable: {plate_error}",
        "elapsed_ms": round(elapsed_ms, 2),
        "image_size": {"width": int(image.shape[1]), "height": int(image.shape[0])},
        "count": len(detections),
        "detections": detections,
        "full_image_plates": full_image_plates,
        "annotated_image": f"/outputs/{output_name}",
    }


def draw_tracking_frame(
    result: Any,
    frame: np.ndarray,
    vehicles_only: bool,
    min_box_area: int,
    plates: list[dict[str, Any]] | None = None,
) -> np.ndarray:
    annotated = frame.copy()
    vehicle_boxes: list[list[int]] = []
    associated_plate_boxes: list[list[int]] = []
    boxes = result.boxes
    if boxes is not None and len(boxes) > 0:
        names = result.names
        xyxy = boxes.xyxy.cpu().numpy()
        classes = boxes.cls.cpu().numpy().astype(int)
        confs = boxes.conf.cpu().numpy()
        ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else [None] * len(xyxy)

        for box, cls_id, det_conf, track_id in zip(xyxy, classes, confs, ids):
            x1, y1, x2, y2 = [int(v) for v in box]
            bbox = [x1, y1, x2, y2]
            box_area = max(0, x2 - x1) * max(0, y2 - y1)
            class_name = names.get(int(cls_id), str(cls_id))
            if vehicles_only and not is_vehicle_class(class_name):
                continue
            if box_area < min_box_area:
                continue

            color = (36, 107, 253) if is_vehicle_class(class_name) else (245, 158, 11)
            label = f"{class_name} {det_conf:.2f}"
            if track_id is not None:
                label = f"id:{int(track_id)} {label}"
            vehicle_crop_plates: list[dict[str, Any]] = []
            if is_vehicle_class(class_name):
                crop = frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
                if crop.size:
                    vehicle_crop_plates = detect_plates(crop, min_confidence=0.0)
                if vehicle_crop_plates:
                    label += f" {vehicle_crop_plates[0]['text']}"
            draw_label(annotated, bbox, label, color)
            if is_vehicle_class(class_name):
                vehicle_boxes.append(bbox)
                for plate in vehicle_crop_plates:
                    local_box = plate.get("bbox")
                    if not local_box:
                        continue
                    px1, py1, px2, py2 = [int(v) for v in local_box]
                    global_plate_box = [x1 + px1, y1 + py1, x1 + px2, y1 + py2]
                    associated_plate_boxes.append(global_plate_box)
                    draw_label(annotated, global_plate_box, f"plate {plate['text']}", (20, 184, 166))

    for plate in plates or []:
        bbox = plate.get("bbox")
        if not bbox:
            continue
        plate_box = [int(v) for v in bbox]
        if any(box_iou(plate_box, used_box) > 0.35 for used_box in associated_plate_boxes):
            continue
        draw_label(annotated, plate_box, f"plate {plate['text']}", (20, 184, 166))
        if any(box_iou(plate_box, vehicle_box) > 0.02 for vehicle_box in vehicle_boxes):
            continue
        derived_box = plate_to_vehicle_box(plate_box, frame.shape)
        draw_label(annotated, derived_box, f"plate-derived vehicle {plate['text']}", (14, 165, 233))
        vehicle_boxes.append(derived_box)
    return annotated


def mjpeg_generator(source: str, conf: float, imgsz: int, model_name: str, vehicles_only: bool, min_box_area: int):
    detector = load_detector(model_name)
    cap = cv2.VideoCapture(0 if source == "camera" else source)
    if not cap.isOpened():
        raise HTTPException(status_code=400, detail=f"Cannot open video source: {source}")

    frame_index = 0
    last_plates: list[dict[str, Any]] = []
    effective_conf = min(conf, 0.30)
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame_index += 1
            if frame_index % 3 == 1:
                last_plates = detect_plates(frame, min_confidence=0.0)
            results = detector.track(
                frame,
                conf=effective_conf,
                imgsz=imgsz,
                tracker="bytetrack.yaml",
                persist=True,
                verbose=False,
            )
            annotated = draw_tracking_frame(
                results[0],
                frame,
                vehicles_only=vehicles_only,
                min_box_area=min_box_area,
                plates=last_plates,
            )
            ok, buffer = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                continue
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
    finally:
        cap.release()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "weights": {
            "yolov11s_visdrone": VISDRONE_MODEL.exists(),
            "fallback_yolo11s": FALLBACK_MODEL.exists(),
            "active": str(active_model_path.name if active_model_path else "not loaded"),
        },
        "hyperlpr3": plate_error or "ready/not loaded",
    }


@app.post("/api/infer/image")
async def infer_upload(
    image: UploadFile = File(...),
    conf: float = Form(0.25),
    imgsz: int = Form(960),
    model_name: str = Form("auto"),
) -> JSONResponse:
    frame = image_from_upload(await image.read())
    return JSONResponse(infer_image(frame, conf=conf, imgsz=imgsz, model_name=model_name))


@app.post("/api/infer/base64")
async def infer_base64(payload: dict[str, Any]) -> JSONResponse:
    raw = payload.get("image", "")
    if "," in raw:
        raw = raw.split(",", 1)[1]
    frame = image_from_upload(base64.b64decode(raw))
    return JSONResponse(
        infer_image(
            frame,
            conf=float(payload.get("conf", 0.25)),
            imgsz=int(payload.get("imgsz", 960)),
            model_name=str(payload.get("model_name", "auto")),
        )
    )


@app.get("/api/stream/mjpeg")
def stream_mjpeg(
    source: str = "camera",
    conf: float = 0.30,
    imgsz: int = 960,
    model_name: str = "auto",
    vehicles_only: bool = True,
    min_box_area: int = 1200,
) -> StreamingResponse:
    return StreamingResponse(
        mjpeg_generator(
            source=source,
            conf=conf,
            imgsz=imgsz,
            model_name=model_name,
            vehicles_only=vehicles_only,
            min_box_area=min_box_area,
        ),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
