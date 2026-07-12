from __future__ import annotations

import threading

from app.schemas.video import CameraCreateRequest, CameraSource, CameraStatusItem, VideoStatus
from app.services.video_stream import VideoStreamService


SANDTABLE_CAMERAS: list[CameraSource] = [
    CameraSource(camera_id="live1", name="桥面", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live1", location="沙盘桥面"),
    CameraSource(camera_id="live2", name="停车场出口", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live2", location="停车场出口"),
    CameraSource(camera_id="live3", name="行人检测", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live3", location="行人检测区"),
    CameraSource(camera_id="live4", name="消防车识别", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live4", location="消防车识别区"),
    CameraSource(camera_id="live5", name="桥出口", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live5", location="桥出口"),
    CameraSource(camera_id="live6", name="桥入口", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live6", location="桥入口"),
    CameraSource(camera_id="live7", name="道路 2", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live7", location="道路 2"),
    CameraSource(camera_id="live8", name="隧道事故识别", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live8", location="隧道事故识别"),
    CameraSource(camera_id="live9", name="隧道车辆数量", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live9", location="隧道车辆数量"),
    CameraSource(camera_id="live10", name="道路 3", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live10", location="道路 3"),
    CameraSource(camera_id="live11", name="停车场入口", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live11", location="停车场入口"),
    CameraSource(camera_id="live12", name="道路 1", type="sandtable", stream_url="rtsp://10.126.59.120:8554/live/live12", location="道路 1"),
]

MAX_ACTIVE_STREAMS = 4


class CameraHub:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sources: dict[str, CameraSource] = {item.camera_id: item for item in SANDTABLE_CAMERAS}
        self._streams: dict[str, VideoStreamService] = {item.camera_id: VideoStreamService() for item in SANDTABLE_CAMERAS}
        self.current_camera_id: str = "live1"
        self._start_order: list[str] = []

    def list_sources(self) -> list[CameraSource]:
        result = []
        for camera_id, source in self._sources.items():
            status = self._streams[camera_id].status()
            result.append(
                source.model_copy(
                    update={
                        "status": (
                            "online"
                            if status.connected
                            else "error"
                            if status.last_error
                            else "connecting"
                            if status.running
                            else "offline"
                        ),
                        "selected": camera_id == self.current_camera_id,
                    }
                )
            )
        return result

    def get_source(self, camera_id: str) -> CameraSource:
        return self._sources[camera_id]

    def add_source(self, req: CameraCreateRequest) -> CameraSource:
        with self._lock:
            camera_id = f"custom{len([key for key in self._sources if key.startswith('custom')]) + 1}"
            source = CameraSource(camera_id=camera_id, **req.model_dump(), status="offline")
            self._sources[camera_id] = source
            self._streams[camera_id] = VideoStreamService()
            return source

    def start(self, camera_id: str) -> VideoStatus:
        with self._lock:
            source = self._sources[camera_id]
            stream = self._streams[camera_id]
            current_status = stream.status()
            if current_status.running and current_status.connected:
                self.current_camera_id = camera_id
                self._start_order = [item for item in self._start_order if item != camera_id]
                self._start_order.append(camera_id)
                return VideoStatus(**current_status.__dict__)
            active_ids = [
                active_id
                for active_id in self._start_order
                if active_id in self._streams and self._streams[active_id].status().running
            ]
            while len(active_ids) >= MAX_ACTIVE_STREAMS:
                oldest_id = active_ids.pop(0)
                if oldest_id != camera_id:
                    self._streams[oldest_id].stop()
                    self._start_order = [item for item in self._start_order if item != oldest_id]
            self.current_camera_id = camera_id
            self._start_order = [item for item in self._start_order if item != camera_id]
            self._start_order.append(camera_id)
            return VideoStatus(**stream.start(source.stream_url).__dict__)

    def start_custom(self, source: str, name: str | None = None, location: str | None = None) -> CameraSource:
        req = CameraCreateRequest(
            name=name or "手动视频源",
            type="phone" if source.startswith(("http://", "https://")) else "custom",
            stream_url=source,
            location=location or "手动接入",
            description="手动输入的视频源，可用于手机 IP Webcam、USB 摄像头或本地视频。",
        )
        camera = self.add_source(req)
        self.start(camera.camera_id)
        return camera

    def stop(self, camera_id: str) -> VideoStatus:
        with self._lock:
            self._start_order = [item for item in self._start_order if item != camera_id]
            return VideoStatus(**self._streams[camera_id].stop().__dict__)

    def stop_all(self) -> list[CameraStatusItem]:
        for stream in self._streams.values():
            stream.stop()
        self._start_order = []
        return self.status_all()

    def status(self, camera_id: str) -> VideoStatus:
        return VideoStatus(**self._streams[camera_id].status().__dict__)

    def status_all(self) -> list[CameraStatusItem]:
        return [
            CameraStatusItem(camera_id=camera_id, status=VideoStatus(**stream.status().__dict__))
            for camera_id, stream in self._streams.items()
        ]

    def mjpeg_frames(self, camera_id: str):
        return self._streams[camera_id].mjpeg_frames()

    def latest_jpeg(self, camera_id: str) -> bytes | None:
        return self._streams[camera_id].latest_jpeg()
