from __future__ import annotations

import base64
from datetime import datetime
from uuid import uuid4

import httpx

from app.schemas.dashboard import (
    AlgorithmServiceConfig,
    AlgorithmServiceState,
    AnalysisResult,
    DetectionConfig,
    TrafficEvent,
)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class AlgorithmClient:
    def __init__(self) -> None:
        self.config = AlgorithmServiceConfig()
        self.detection_config = DetectionConfig()
        self.status = "not_configured"
        self.message = "Algorithm service is not configured."
        self.last_checked_at: str | None = None
        self.latest_result = AnalysisResult(
            timestamp=now_iso(),
            model_id=None,
            error="No algorithm result yet. Connect algorithm service or push an analysis result.",
        )
        self.events: list[TrafficEvent] = []

    def get_state(self) -> AlgorithmServiceState:
        return AlgorithmServiceState(
            config=self.config,
            status=self.status,
            message=self.message,
            last_checked_at=self.last_checked_at,
        )

    def update_config(self, config: AlgorithmServiceConfig) -> AlgorithmServiceState:
        self.config = config
        self.status = "offline" if config.enabled and config.base_url else "not_configured"
        self.message = "Algorithm service configured." if config.enabled and config.base_url else "Algorithm service is disabled."
        return self.get_state()

    def update_detection_config(self, config: DetectionConfig) -> DetectionConfig:
        self.detection_config = config
        return self.detection_config

    async def health(self) -> AlgorithmServiceState:
        self.last_checked_at = now_iso()
        if not self.config.enabled or not self.config.base_url:
            self.status = "not_configured"
            self.message = "Algorithm service is not enabled."
            return self.get_state()

        url = self.config.base_url.rstrip("/") + self.config.health_path
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.get(url)
            response.raise_for_status()
            self.status = "ready"
            self.message = f"Connected to {url}"
        except Exception as exc:  # noqa: BLE001 - returned to UI for setup debugging
            self.status = "error"
            self.message = str(exc)
        return self.get_state()

    def push_result(self, result: AnalysisResult) -> AnalysisResult:
        normalized = result.model_copy(update={"timestamp": result.timestamp or now_iso()})
        self.latest_result = normalized
        new_events: list[TrafficEvent] = []
        seen_keys = {
            (event.type, event.camera_id, event.description)
            for event in self.events[:30]
        }
        for event in normalized.events:
            key = (event.type, event.camera_id, event.description)
            if key not in seen_keys:
                new_events.append(event)
                seen_keys.add(key)
        self.events = new_events + self.events
        self.events = self.events[:100]
        if self.status == "not_configured":
            self.status = "ready"
            self.message = "Receiving pushed algorithm results."
        return self.latest_result

    async def infer_frame(self, camera_id: str, jpeg: bytes | None) -> AnalysisResult:
        if jpeg is None:
            self.latest_result = AnalysisResult(
                timestamp=now_iso(),
                camera_id=camera_id,
                error="No frame available for this camera. Start the camera stream first.",
            )
            return self.latest_result

        if not self.config.enabled or not self.config.base_url:
            self.latest_result = AnalysisResult(
                timestamp=now_iso(),
                camera_id=camera_id,
                error="Algorithm service is not configured. Start the model service and set base URL.",
            )
            return self.latest_result

        url = self.config.base_url.rstrip("/") + self.config.infer_path
        payload = {
            "camera_id": camera_id,
            "image_base64": base64.b64encode(jpeg).decode("ascii"),
            "config": self.detection_config.model_dump(),
        }
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            result = AnalysisResult.model_validate(data)
            return self.push_result(result)
        except Exception as exc:  # noqa: BLE001 - returned to UI for setup debugging
            event = TrafficEvent(
                event_id=f"evt_{uuid4().hex[:10]}",
                type="algorithm",
                severity="warning",
                description=f"Algorithm request failed: {exc}",
                created_at=now_iso(),
                camera_id=camera_id,
            )
            self.latest_result = AnalysisResult(timestamp=now_iso(), camera_id=camera_id, events=[event], error=str(exc))
            self.events = [event] + self.events[:99]
            self.status = "error"
            self.message = str(exc)
            return self.latest_result
