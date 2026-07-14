from __future__ import annotations

from collections import deque
from datetime import datetime
from threading import Lock
import time
from typing import Any

from app.services.system_monitor import system_monitor


class AdaptiveModelScheduler:
    """Select a stable inference profile from task and machine load."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._enabled = True
        self._last_profile: dict[str, dict[str, Any]] = {}
        self._profile_changed_at: dict[str, float] = {}
        self._decisions: deque[dict[str, Any]] = deque(maxlen=120)
        self._resource_cache: dict[str, Any] = {}
        self._resource_cache_at = 0.0

    def configure(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            self._enabled = bool(enabled)
        return self.snapshot()

    def choose(
        self,
        camera_id: str,
        task_mode: str,
        requested_model: str,
        confidence: float,
        inference_size: int,
        interval_ms: int,
        latest_inference_ms: float | None = None,
        is_static_image: bool = False,
    ) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if now - self._resource_cache_at >= 1.5 or not self._resource_cache:
                self._resource_cache = system_monitor.snapshot(latest_inference_ms)
                self._resource_cache_at = now
            resources = dict(self._resource_cache)
        gpu = resources.get("gpu") or {}
        cpu = resources.get("cpu") or {}
        memory = resources.get("memory") or {}
        gpu_usage = float(gpu.get("usage_percent") or 0)
        gpu_memory = float(gpu.get("memory_usage_percent") or 0)
        cpu_usage = float(cpu.get("usage_percent") or 0)
        memory_usage = float(memory.get("usage_percent") or 0)
        inference_ms = float(latest_inference_ms or 0)

        profile = "balanced"
        reasons: list[str] = []
        model_name = requested_model
        conf = confidence
        imgsz = inference_size
        interval = interval_ms

        if not self._enabled:
            profile = "manual"
            reasons.append("自适应调度已关闭，使用人工配置")
        elif is_static_image:
            profile = "quality"
            imgsz = max(960, inference_size)
            interval = max(400, interval_ms)
            conf = min(confidence, 0.28)
            reasons.append("静态图片优先识别精度")
        elif task_mode == "road_anomaly":
            profile = "anomaly"
            imgsz = max(768, min(960, inference_size))
            interval = max(180, interval_ms)
            conf = min(confidence, 0.25)
            reasons.append("道路异常任务保留小目标分辨率")
        elif gpu_memory >= 88 or memory_usage >= 92 or cpu_usage >= 92:
            profile = "protect"
            model_name = "fallback"
            imgsz = min(inference_size, 512)
            interval = max(interval_ms, 350)
            reasons.append("系统资源接近上限，启用保护策略")
        elif gpu_usage >= 88 or inference_ms >= 150:
            profile = "realtime"
            imgsz = min(inference_size, 640)
            interval = max(interval_ms, 180)
            reasons.append("推理负载较高，优先实时性")
        elif gpu.get("available") and gpu_usage <= 72 and gpu_memory <= 75 and inference_ms <= 95:
            profile = "quality"
            imgsz = max(inference_size, 768)
            interval = max(80, min(interval_ms, 140))
            reasons.append("GPU 余量充足，提高小目标识别质量")
        else:
            reasons.append("资源负载正常，使用均衡策略")

        decision = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "camera_id": camera_id,
            "task_mode": task_mode,
            "profile": profile,
            "model_name": model_name,
            "confidence": round(conf, 3),
            "inference_size": int(imgsz),
            "detection_interval_ms": int(interval),
            "reason": "；".join(reasons),
            "metrics": {
                "cpu_percent": cpu_usage,
                "memory_percent": memory_usage,
                "gpu_percent": gpu_usage if gpu.get("available") else None,
                "gpu_memory_percent": gpu_memory if gpu.get("available") else None,
                "inference_ms": latest_inference_ms,
            },
        }
        with self._lock:
            previous = self._last_profile.get(camera_id)
            last_changed = self._profile_changed_at.get(camera_id, 0.0)
            if (
                previous
                and previous.get("profile") != decision.get("profile")
                and decision.get("profile") != "protect"
                and now - last_changed < 8.0
            ):
                return previous
            self._last_profile[camera_id] = decision
            if not previous or any(previous.get(key) != decision.get(key) for key in ("profile", "model_name", "inference_size", "detection_interval_ms")):
                self._profile_changed_at[camera_id] = now
                self._decisions.appendleft(decision)
        return decision

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "active": list(self._last_profile.values()),
                "decisions": list(self._decisions),
            }


adaptive_model_scheduler = AdaptiveModelScheduler()
