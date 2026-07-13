from __future__ import annotations

from datetime import datetime
from typing import Any

import psutil


GIB = 1024**3


class SystemMonitor:
    def __init__(self) -> None:
        psutil.cpu_percent(interval=None)

    def _gpu_metrics(self) -> dict[str, Any]:
        try:
            import pynvml

            pynvml.nvmlInit()
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode("utf-8", errors="replace")
                return {
                    "available": True,
                    "name": str(name),
                    "usage_percent": float(utilization.gpu),
                    "memory_usage_percent": round(memory.used / memory.total * 100, 1),
                    "memory_used_gb": round(memory.used / GIB, 2),
                    "memory_total_gb": round(memory.total / GIB, 2),
                    "temperature_c": int(
                        pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                    ),
                }
            finally:
                pynvml.nvmlShutdown()
        except Exception as exc:
            return {
                "available": False,
                "name": None,
                "usage_percent": None,
                "memory_usage_percent": None,
                "memory_used_gb": None,
                "memory_total_gb": None,
                "temperature_c": None,
                "error": str(exc),
            }

    def snapshot(self, inference_ms: float | None = None) -> dict[str, Any]:
        memory = psutil.virtual_memory()
        process = psutil.Process()
        return {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "cpu": {
                "usage_percent": float(psutil.cpu_percent(interval=None)),
                "physical_cores": psutil.cpu_count(logical=False),
                "logical_cores": psutil.cpu_count(logical=True),
            },
            "memory": {
                "usage_percent": float(memory.percent),
                "used_gb": round(memory.used / GIB, 2),
                "total_gb": round(memory.total / GIB, 2),
            },
            "gpu": self._gpu_metrics(),
            "backend_process": {
                "memory_mb": round(process.memory_info().rss / 1024**2, 1),
            },
            "inference": {
                "latest_ms": inference_ms,
            },
        }


system_monitor = SystemMonitor()
