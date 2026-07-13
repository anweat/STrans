from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.schemas.dashboard import AnalysisResult, DetectionBox, TrafficEvent
from app.services.local_model import vehicle_visual_features


MODEL_ROOT = Path("D:/models/STrans")
VISDRONE_MODEL = MODEL_ROOT / "detect/yolov11s-visdrone/weights/best.pt"
RDD_MODEL = MODEL_ROOT / "detect/rdd-yolo12s/yolo12s_RDD2022_best.pt"
POTHOLE_MODEL = MODEL_ROOT / "detect/pothole-yolov8-vinoth/best.pt"

LEGAL_TRAFFIC_CLASSES = {
    "person",
    "pedestrian",
    "people",
    "bicycle",
    "car",
    "van",
    "truck",
    "tricycle",
    "awning-tricycle",
    "bus",
    "motor",
    "motorcycle",
}


def now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def normalize_class_name(value: str) -> str:
    return value.lower().strip().replace("_", "-")


def box_area(box: list[float]) -> float:
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def box_iou(first: list[float], second: list[float]) -> float:
    ax1, ay1, ax2, ay2 = first
    bx1, by1, bx2, by2 = second
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    intersection = box_area([ix1, iy1, ix2, iy2])
    if intersection <= 0:
        return 0.0
    union = box_area(first) + box_area(second) - intersection
    return intersection / max(union, 1.0)


def coverage(candidate: list[float], blocker: list[float]) -> float:
    cx1, cy1, cx2, cy2 = candidate
    bx1, by1, bx2, by2 = blocker
    ix1, iy1 = max(cx1, bx1), max(cy1, by1)
    ix2, iy2 = min(cx2, bx2), min(cy2, by2)
    return box_area([ix1, iy1, ix2, iy2]) / max(box_area(candidate), 1.0)


def event_key(event: TrafficEvent) -> tuple[str, str | None, str]:
    return event.type, event.camera_id, event.description


@dataclass
class CameraState:
    baseline_gray: np.ndarray | None = None
    previous_gray: np.ndarray | None = None
    frame_count: int = 0
    last_damage_at: float = 0.0
    # A departing tracked person/vehicle changes the background for a few frames.
    # Keep its last box briefly so frame differencing does not turn that departure
    # into a false "road obstacle" alarm.
    recent_legal_boxes: list[tuple[list[float], int]] = field(default_factory=list)
    # Frame-difference candidates must survive three observations before they
    # become an alarm.  This rejects transient compression noise and moving
    # camera texture while keeping the delay short for a fixed sandtable view.
    pending_obstacles: list[tuple[list[int], int, int]] = field(default_factory=list)
    pending_static_obstacles: list[tuple[list[int], int, int]] = field(default_factory=list)
    unstable_frames: int = 0


class RoadAnomalyService:
    def __init__(self) -> None:
        self._states: dict[str, CameraState] = {}
        self._damage_models: dict[str, Any] = {}
        self._device = "cpu"
        try:
            import torch

            self._device = "0" if torch.cuda.is_available() else "cpu"
        except Exception:
            self._device = "cpu"

    def health(self) -> dict[str, Any]:
        return {
            "workflow": "ROI + frame difference + YOLO/ByteTrack explanation + road-damage supplement",
            "device": self._device,
            "models": {
                "traffic": {
                    "yolo11n": (MODEL_ROOT / "detect/yolo11n/yolo11n.pt").exists(),
                    "yolov8n": (MODEL_ROOT / "detect/yolov8n/yolov8n.pt").exists(),
                    "yolov11s_visdrone": VISDRONE_MODEL.exists(),
                },
                "road_damage": {
                    "rdd_yolo12s": RDD_MODEL.exists(),
                    "pothole_yolov8_vinoth": POTHOLE_MODEL.exists(),
                },
            },
        }

    def reset(self, camera_id: str | None = None) -> None:
        if camera_id:
            self._states.pop(camera_id, None)
        else:
            self._states.clear()

    def analyze_jpeg(
        self,
        camera_id: str,
        jpeg: bytes | None,
        base_result: AnalysisResult | None = None,
        include_damage_model: bool = False,
        include_static_scene: bool = True,
    ) -> AnalysisResult:
        if not jpeg:
            return base_result or AnalysisResult(timestamp=now_iso(), camera_id=camera_id, error="No frame available.")
        array = np.frombuffer(jpeg, dtype=np.uint8)
        frame = cv2.imdecode(array, cv2.IMREAD_COLOR)
        if frame is None:
            return base_result or AnalysisResult(timestamp=now_iso(), camera_id=camera_id, error="Invalid JPEG frame.")
        return self.analyze_frame(
            camera_id,
            frame,
            base_result=base_result,
            include_damage_model=include_damage_model,
            include_static_scene=include_static_scene,
        )

    def annotate_jpeg(self, jpeg: bytes | None, result: AnalysisResult) -> bytes | None:
        """Render only anomaly-mode detections, keeping traffic annotations out."""
        if not jpeg:
            return None
        frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return None
        for detection in result.detections:
            x1, y1, x2, y2 = [int(value) for value in detection.bbox]
            kind = normalize_class_name(detection.class_name)
            if kind == "pedestrian":
                color, label = (37, 197, 255), "pedestrian"
            elif kind.startswith("road-damage"):
                color, label = (42, 126, 238), "road damage"
            else:
                color, label = (32, 156, 245), "road obstacle"
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                f"{label} {float(detection.confidence):.2f}",
                (x1, max(22, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.62,
                color,
                2,
                cv2.LINE_AA,
            )
        ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        return buffer.tobytes() if ok else None

    def analyze_frame(
        self,
        camera_id: str,
        frame: np.ndarray,
        base_result: AnalysisResult | None = None,
        include_damage_model: bool = False,
        include_static_scene: bool = True,
    ) -> AnalysisResult:
        started = time.perf_counter()
        result = base_result or AnalysisResult(timestamp=now_iso(), camera_id=camera_id)
        result = result.model_copy(deep=True)
        result.timestamp = result.timestamp or now_iso()
        result.camera_id = result.camera_id or camera_id
        result.source_width = result.source_width or int(frame.shape[1])
        result.source_height = result.source_height or int(frame.shape[0])

        state = self._states.setdefault(camera_id, CameraState())
        state.frame_count += 1
        roi_mask = self._road_roi_mask(camera_id, frame.shape[:2])
        gray = self._preprocess(frame, roi_mask)

        anomaly_boxes = self._frame_difference_candidates(camera_id, gray, roi_mask, result)
        static_boxes = self._static_scene_candidates(frame, roi_mask, result) if include_static_scene else []
        if static_boxes:
            anomaly_boxes = self._merge_candidates(anomaly_boxes, static_boxes)
        damage_boxes = self._road_damage_candidates(camera_id, frame, include_damage_model)

        new_detections: list[DetectionBox] = []
        new_events: list[TrafficEvent] = []
        for box, score in anomaly_boxes[:6]:
            new_detections.append(
                DetectionBox(
                    bbox=[float(v) for v in box],
                    class_name="road_obstacle_candidate",
                    confidence=score,
                    camera_id=camera_id,
                )
            )
            new_events.append(
                TrafficEvent(
                    type="road_obstacle",
                    severity="warning",
                    description="道路 ROI 内出现无法由车辆/行人解释的异常变化，建议复核疑似障碍物。",
                    camera_id=camera_id,
                    bbox=[float(v) for v in box],
                )
            )

        for box, score, name in damage_boxes[:3]:
            new_detections.append(
                DetectionBox(
                    bbox=[float(v) for v in box],
                    class_name=f"road_damage:{name}",
                    confidence=score,
                    camera_id=camera_id,
                )
            )
            new_events.append(
                TrafficEvent(
                    type="road_damage",
                    severity="warning",
                    description=f"道路破损补充模型检测到 {name}，建议复核。",
                    camera_id=camera_id,
                    bbox=[float(v) for v in box],
                )
            )

        result.detections = result.detections + new_detections
        seen = {event_key(event) for event in result.events}
        for event in new_events:
            if event_key(event) not in seen:
                result.events.append(event)
                seen.add(event_key(event))

        raw = dict(result.raw or {})
        raw["road_anomaly"] = {
            "workflow": "roi_frame_diff_yolo_explain",
            "roi_enabled": True,
            "candidate_count": len(anomaly_boxes),
            "static_scene_candidate_count": len(static_boxes),
            "damage_candidate_count": len(damage_boxes),
            "damage_model_used": include_damage_model,
            "device": self._device,
        }
        result.raw = raw
        elapsed_ms = (time.perf_counter() - started) * 1000
        result.inference_ms = round((result.inference_ms or 0) + elapsed_ms, 2)
        self._update_baseline(state, gray, not anomaly_boxes)
        return result

    def _road_roi_mask(self, camera_id: str, shape: tuple[int, int]) -> np.ndarray:
        height, width = shape
        mask = np.zeros((height, width), dtype=np.uint8)
        # The calibrated live3 view is landscape. Custom phone/video sources can
        # be portrait and often show a much wider multi-lane road; applying the
        # live3 trapezoid to those sources cuts real obstacles out of the ROI.
        use_live3_roi = camera_id == "live3" or (camera_id.startswith("custom") and width >= height)
        if use_live3_roi:
            points = np.array(
                [
                    [int(width * 0.30), int(height * 0.11)],
                    [int(width * 0.60), int(height * 0.11)],
                    [int(width * 0.77), int(height * 0.82)],
                    [int(width * 0.13), int(height * 0.82)],
                ],
                dtype=np.int32,
            )
        else:
            points = np.array(
                [
                    [int(width * 0.18), int(height * 0.08)],
                    [int(width * 0.82), int(height * 0.08)],
                    [int(width * 0.96), int(height * 0.96)],
                    [int(width * 0.04), int(height * 0.96)],
                ],
                dtype=np.int32,
            )
        cv2.fillPoly(mask, [points], 255)
        return mask

    def _preprocess(self, frame: np.ndarray, roi_mask: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        return cv2.bitwise_and(gray, roi_mask)

    def _frame_difference_candidates(
        self,
        camera_id: str,
        gray: np.ndarray,
        roi_mask: np.ndarray,
        result: AnalysisResult,
    ) -> list[tuple[list[int], float]]:
        state = self._states.setdefault(camera_id, CameraState())
        if state.baseline_gray is None or state.baseline_gray.shape != gray.shape:
            state.baseline_gray = gray.copy()
            state.previous_gray = gray.copy()
            return []

        global_motion = self._global_camera_motion(state.previous_gray, gray)
        state.previous_gray = gray.copy()
        if global_motion > 2.5:
            # A hand passing through the fixed camera must not become the new
            # background. Hold the last clean baseline through short global
            # disturbances; only re-seed after a sustained camera move.
            state.unstable_frames += 1
            if state.unstable_frames >= 12:
                state.baseline_gray = gray.copy()
                state.pending_obstacles = []
                state.unstable_frames = 0
            return []

        diff = cv2.absdiff(gray, state.baseline_gray)
        diff = cv2.bitwise_and(diff, roi_mask)
        threshold_value = max(28, int(np.mean(diff[roi_mask > 0]) + np.std(diff[roi_mask > 0]) * 2.2))
        _, binary = cv2.threshold(diff, threshold_value, 255, cv2.THRESH_BINARY)
        kernel = np.ones((5, 5), dtype=np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)

        # A moving/handheld/vehicle-mounted camera makes a large part of the
        # road change between frames.  Frame differencing is not meaningful in
        # that situation and would turn pavement texture into many obstacles.
        # Sandtable RTSP cameras are fixed, while public dashcam samples often
        # are not, so fall back to the specialised road-damage model there.
        roi_pixels = max(int(cv2.countNonZero(roi_mask)), 1)
        changed_ratio = cv2.countNonZero(binary) / roi_pixels
        if changed_ratio > 0.085:
            state.unstable_frames += 1
            if state.unstable_frames >= 12:
                state.baseline_gray = gray.copy()
                state.pending_obstacles = []
                state.unstable_frames = 0
            return []
        state.unstable_frames = 0

        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        height, width = gray.shape[:2]
        min_area = max(350.0, width * height * 0.00045)
        legal_boxes = [
            item.bbox
            for item in result.detections
            if normalize_class_name(item.class_name) in LEGAL_TRAFFIC_CLASSES
        ]
        if legal_boxes:
            state.recent_legal_boxes.extend((list(box), state.frame_count) for box in legal_boxes)
        state.recent_legal_boxes = [
            (box, seen_at)
            for box, seen_at in state.recent_legal_boxes
            if state.frame_count - seen_at <= 8
        ]
        # Include recently observed legal targets for roughly four seconds at the
        # normal 500 ms inference interval. This covers both entering and leaving
        # motion without masking a genuinely static obstacle elsewhere on the road.
        legal_boxes.extend(box for box, _ in state.recent_legal_boxes)

        candidates: list[tuple[list[int], float]] = []
        for contour in contours:
            area = float(cv2.contourArea(contour))
            # An obstacle is local. A region covering most of a lane is caused
            # by lighting, a vehicle shadow or baseline drift, not debris.
            if area < min_area or area > width * height * 0.018:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if w < 10 or h < 10:
                continue
            box = [x, y, x + w, y + h]
            if any(box_iou(box, legal) > 0.04 or coverage(box, legal) > 0.35 for legal in legal_boxes):
                continue
            score = min(0.95, max(0.35, area / max(width * height * 0.015, 1.0)))
            candidates.append((box, round(float(score), 3)))
        return self._confirmed_motion_candidates(state, candidates)

    @staticmethod
    def _global_camera_motion(previous: np.ndarray | None, current: np.ndarray) -> float:
        if previous is None or previous.shape != current.shape:
            return 0.0
        points = cv2.goodFeaturesToTrack(previous, maxCorners=120, qualityLevel=0.015, minDistance=12)
        if points is None or len(points) < 12:
            return 0.0
        next_points, status, _ = cv2.calcOpticalFlowPyrLK(previous, current, points, None)
        if next_points is None or status is None:
            return 0.0
        valid = status.reshape(-1) == 1
        if int(np.count_nonzero(valid)) < 12:
            return 0.0
        deltas = (next_points[valid] - points[valid]).reshape(-1, 2)
        return float(np.median(np.linalg.norm(deltas, axis=1)))

    @staticmethod
    def _confirmed_motion_candidates(
        state: CameraState,
        candidates: list[tuple[list[int], float]],
    ) -> list[tuple[list[int], float]]:
        previous = [item for item in state.pending_obstacles if state.frame_count - item[2] <= 2]
        updated: list[tuple[list[int], int, int]] = []
        confirmed: list[tuple[list[int], float]] = []
        for box, score in candidates:
            match_index = next((index for index, item in enumerate(previous) if box_iou(box, item[0]) >= 0.30), None)
            if match_index is None:
                hits = 1
            else:
                _, prior_hits, _ = previous.pop(match_index)
                hits = prior_hits + 1
            updated.append((box, hits, state.frame_count))
            if hits >= 3:
                confirmed.append((box, score))
        state.pending_obstacles = updated
        return sorted(confirmed, key=lambda item: item[1], reverse=True)

    def _static_scene_candidates(
        self,
        frame: np.ndarray,
        roi_mask: np.ndarray,
        result: AnalysisResult,
    ) -> list[tuple[list[int], float]]:
        """Find large, bright stationary objects when a source is a still image.

        Frame differencing cannot discover an obstacle already present in the
        first frame of a JPG source. This is intentionally an anomaly-mode-only
        supplement: well-explained traffic boxes mask their own highlights,
        leaving unusual objects such as a bottle or cup in the drivable area.
        """
        height, width = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        roi_values = gray[roi_mask > 0]
        threshold_value = max(158, int(np.percentile(roi_values, 82))) if roi_values.size else 158
        _, bright = cv2.threshold(gray, threshold_value, 255, cv2.THRESH_BINARY)
        bright = cv2.bitwise_and(bright, roi_mask)

        # Brightness alone misses tan/brown props under changing exposure. Build
        # a second mask from chroma distance to the dominant road surface. The
        # median is robust to the relatively small number of vehicles/objects in
        # the ROI, while Lab a/b channels are much less sensitive to shadows.
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        roi_lab = lab[roi_mask > 0]
        if roi_lab.size:
            median_a = float(np.median(roi_lab[:, 1]))
            median_b = float(np.median(roi_lab[:, 2]))
            delta_a = lab[:, :, 1].astype(np.float32) - median_a
            delta_b = lab[:, :, 2].astype(np.float32) - median_b
            chroma_distance = cv2.magnitude(delta_a, delta_b)
            chroma_threshold = max(15.0, float(np.percentile(chroma_distance[roi_mask > 0], 82)))
            chromatic = np.where(chroma_distance >= chroma_threshold, 255, 0).astype(np.uint8)
            chromatic = cv2.bitwise_and(chromatic, roi_mask)
        else:
            chromatic = np.zeros_like(gray)

        hard_explained_boxes: list[list[float]] = []
        soft_explained_boxes: list[list[float]] = []
        for item in result.detections:
            if normalize_class_name(item.class_name) not in LEGAL_TRAFFIC_CLASSES:
                continue
            if item.plate:
                hard_explained_boxes.append(list(item.bbox))
                continue

            x1, y1, x2, y2 = [int(value) for value in item.bbox]
            crop = frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
            if crop.size == 0:
                continue
            crop_height, crop_width = crop.shape[:2]
            # Inspect the body core instead of the whole detector rectangle.
            # Road markings and trees around a smooth prop otherwise inflate its
            # texture score and let a false car label suppress a real obstacle.
            inner = crop[
                int(crop_height * 0.08):max(int(crop_height * 0.92), 1),
                int(crop_width * 0.12):max(int(crop_width * 0.88), 1),
            ]
            features = vehicle_visual_features(inner if inner.size else crop)
            # An unplated YOLO label is soft evidence in anomaly mode. Real toy
            # vehicles still have dense body edges and texture, while bottle
            # caps, erasers and cups are commonly smooth despite receiving a
            # car/truck class from the generic detector.
            if (
                float(item.confidence) >= 0.24
                and features["edge_density"] >= 0.08
                and features["contrast"] >= 30.0
                and features["entropy"] >= 3.55
            ):
                soft_explained_boxes.append(list(item.bbox))

        # Full-frame OCR sometimes sees a near plate even when YOLO misses the
        # partly clipped vehicle body. Add a conservative proxy only for plates
        # not already associated with a detector box.
        plate_proxies: list[list[float]] = []
        for plate in (result.raw or {}).get("plates") or []:
            plate_box = plate.get("bbox")
            if not plate_box or len(plate_box) != 4:
                continue
            px1, py1, px2, py2 = [int(value) for value in plate_box]
            center_x = (px1 + px2) / 2
            center_y = (py1 + py2) / 2
            if any(
                x1 <= center_x <= x2 and y1 <= center_y <= y2
                for x1, y1, x2, y2 in hard_explained_boxes + soft_explained_boxes
            ):
                continue
            plate_width = max(1, px2 - px1)
            plate_height = max(1, py2 - py1)
            plate_proxies.append(
                [
                    max(0, px1 - int(plate_width * 0.5)),
                    max(0, py1 - int(plate_height * 2.5)),
                    min(width, px2 + int(plate_width * 0.5)),
                    min(height, py2 + int(plate_height * 0.5)),
                ]
            )

        close_kernel = np.ones((7, 7), dtype=np.uint8)
        open_kernel = np.ones((3, 3), dtype=np.uint8)
        bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, close_kernel)
        bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, open_kernel)
        chromatic = cv2.morphologyEx(chromatic, cv2.MORPH_CLOSE, close_kernel)
        chromatic = cv2.morphologyEx(chromatic, cv2.MORPH_OPEN, open_kernel)
        # Cut known road users out before contour extraction. This preserves the
        # visible remainder of an adjacent obstacle instead of discarding a
        # merged vehicle-plus-object rectangle after the fact.
        # Only hard evidence is removed before contours are built. Soft unplated
        # detections remain visible to the anomaly branch and are arbitrated
        # after the object candidate has independent visual evidence.
        for x1, y1, x2, y2 in hard_explained_boxes + plate_proxies:
            left, top = max(0, int(x1)), max(0, int(y1))
            right, bottom = min(width, int(x2)), min(height, int(y2))
            bright[top:bottom, left:right] = 0
            chromatic[top:bottom, left:right] = 0
        # Keep both channels separate. OR-ing them first can connect an object
        # to a bright lane edge and turn most of the road into one contour.
        bright_contours, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        chromatic_contours, _ = cv2.findContours(chromatic, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contour_sources = [(contour, "bright") for contour in bright_contours]
        contour_sources.extend((contour, "chromatic") for contour in chromatic_contours)

        # Remote sandtable views contain valid debris only a few dozen pixels
        # wide. Keep the lower bound proportional to the frame so portrait and
        # wide shots do not silently discard those objects before scoring.
        min_area = width * height * 0.0008
        max_area = width * height * 0.015
        road_distance = cv2.distanceTransform(roi_mask, cv2.DIST_L2, 5)
        candidates: list[tuple[list[int], float]] = []
        for contour, source_kind in contour_sources:
            area = float(cv2.contourArea(contour))
            if not min_area <= area <= max_area:
                continue
            x, y, box_width, box_height = cv2.boundingRect(contour)
            if box_width < width * 0.025 or box_height < height * 0.025:
                continue
            if box_width * box_height > width * height * 0.025:
                # Sparse color leaking from trees/road edges can have a small
                # contour area but an enormous bounding rectangle.
                continue
            aspect_ratio = box_width / max(box_height, 1)
            if not 0.30 <= aspect_ratio <= 1.35:
                continue
            box = [x, y, x + box_width, y + box_height]
            center_x = min(width - 1, max(0, x + box_width // 2))
            center_y_px = min(height - 1, max(0, y + box_height // 2))
            # Color from trees, LED strips and pavements often leaks a few
            # pixels into the polygon. A real road obstacle must sit inside the
            # drivable region rather than cling to its outer boundary.
            if float(road_distance[center_y_px, center_x]) < width * 0.045:
                continue
            # This is a still-image supplement, not a general object detector.
            # Limit it to bright, upright objects in the middle approach of the
            # road.  Without these guards, white vehicles, road arrows and
            # signal reflections become false obstacle candidates.
            center_y = (y + box_height / 2) / max(height, 1)
            if not 0.16 <= center_y <= 0.84:
                continue
            candidate_gray = gray[y : y + box_height, x : x + box_width]
            if candidate_gray.size == 0 or float(np.mean(candidate_gray)) < 120.0:
                # Colored objects can be darker than the legacy bright-object
                # threshold. Keep them only when the chroma mask covers a
                # meaningful part of the candidate.
                chroma_fill = float(np.count_nonzero(chromatic[y : y + box_height, x : x + box_width])) / max(
                    box_width * box_height,
                    1,
                )
                if chroma_fill < 0.28:
                    continue
            candidate_crop = frame[y : y + box_height, x : x + box_width]
            candidate_features = vehicle_visual_features(candidate_crop)
            hsv_crop = cv2.cvtColor(candidate_crop, cv2.COLOR_BGR2HSV)
            mean_saturation = float(np.mean(hsv_crop[:, :, 1])) if hsv_crop.size else 0.0
            contour_fill = area / max(float(box_width * box_height), 1.0)
            # Painted arrows and dashed lane lines form bright contours but
            # have very little tonal variation. A physical object contributes
            # depth, shadow and multiple intensity bands inside its box.
            if contour_fill < 0.20:
                continue
            if candidate_features["contrast"] < 21.0 or candidate_features["entropy"] < 2.7:
                continue
            # Low-saturation candidates need stronger texture because white
            # arrows and lane separators otherwise dominate the bright mask.
            if mean_saturation < 16.0 and (
                candidate_features["contrast"] < 28.0 or candidate_features["entropy"] < 3.15
            ):
                continue
            # Perspective can make a road object overlap a vehicle behind it.
            # Suppress only when the vehicle explains most of the candidate,
            # not on a small incidental overlap.
            if any(
                box_iou(box, legal) > 0.45 or coverage(box, legal) > 0.68
                for legal in hard_explained_boxes
            ):
                continue
            if any(
                box_iou(box, legal) > 0.40
                and max(coverage(box, legal), coverage(legal, box)) > 0.74
                for legal in soft_explained_boxes
            ):
                continue
            score = min(0.9, max(0.5, area / max(width * height * 0.012, 1.0)))
            if source_kind == "chromatic":
                score = min(0.92, score + 0.04)
            candidates.append((box, round(float(score), 3)))
        candidates = self._merge_candidates([], sorted(candidates, key=lambda item: item[1], reverse=True))
        return self._confirmed_static_candidates(
            self._states.setdefault(result.camera_id or "unknown", CameraState()),
            candidates[:6],
        )

    @staticmethod
    def _confirmed_static_candidates(
        state: CameraState,
        candidates: list[tuple[list[int], float]],
    ) -> list[tuple[list[int], float]]:
        previous = [item for item in state.pending_static_obstacles if state.frame_count - item[2] <= 3]
        updated: list[tuple[list[int], int, int]] = []
        confirmed: list[tuple[list[int], float]] = []
        for box, score in candidates:
            match_index = next((index for index, item in enumerate(previous) if box_iou(box, item[0]) >= 0.35), None)
            hits = 1
            if match_index is not None:
                _, prior_hits, _ = previous.pop(match_index)
                hits = prior_hits + 1
            updated.append((box, hits, state.frame_count))
            if hits >= 2:
                confirmed.append((box, score))
        state.pending_static_obstacles = updated
        return confirmed

    @staticmethod
    def _merge_candidates(
        primary: list[tuple[list[int], float]],
        supplement: list[tuple[list[int], float]],
    ) -> list[tuple[list[int], float]]:
        merged = list(primary)
        for box, score in supplement:
            if any(box_iou(box, existing) > 0.25 for existing, _ in merged):
                continue
            merged.append((box, score))
        return sorted(merged, key=lambda item: item[1], reverse=True)[:3]

    def _update_baseline(self, state: CameraState, gray: np.ndarray, stable: bool) -> None:
        if state.baseline_gray is None:
            state.baseline_gray = gray.copy()
            return
        alpha = 0.03 if stable else 0.005
        state.baseline_gray = cv2.addWeighted(gray, alpha, state.baseline_gray, 1 - alpha, 0)

    def _road_damage_candidates(self, camera_id: str, frame: np.ndarray, enabled: bool) -> list[tuple[list[int], float, str]]:
        if not enabled:
            return []
        state = self._states.setdefault(camera_id, CameraState())
        now = time.monotonic()
        if now - state.last_damage_at < 2.5:
            return []
        state.last_damage_at = now
        model_path = RDD_MODEL if RDD_MODEL.exists() else POTHOLE_MODEL
        if not model_path.exists():
            return []
        try:
            from ultralytics import YOLO

            key = str(model_path)
            model = self._damage_models.get(key)
            if model is None:
                model = YOLO(key)
                self._damage_models[key] = model
            result = model.predict(frame, imgsz=640, conf=0.25, iou=0.45, device=self._device, verbose=False)[0]
        except Exception:
            return []
        if result.boxes is None:
            return []
        boxes = result.boxes.xyxy.cpu().numpy().tolist()
        confs = result.boxes.conf.cpu().numpy().tolist()
        classes = result.boxes.cls.cpu().numpy().astype(int).tolist()
        names = result.names if isinstance(result.names, dict) else {}
        return [
            ([int(round(v)) for v in box], round(float(conf), 3), str(names.get(cls_id, cls_id)))
            for box, conf, cls_id in zip(boxes, confs, classes)
        ]


road_anomaly_service = RoadAnomalyService()
