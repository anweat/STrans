from __future__ import annotations

import threading
import time
from typing import Any

import httpx


BEIJING_FORECAST_URL = (
    "https://api.open-meteo.com/v1/forecast?latitude=39.9042&longitude=116.4074"
    "&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,"
    "rain,showers,snowfall,weather_code,cloud_cover,wind_speed_10m,visibility"
    "&timezone=Asia%2FShanghai"
)
CACHE_SECONDS = 600

WMO_TEXT = {
    0: "晴",
    1: "晴间多云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "毛毛雨",
    53: "毛毛雨",
    55: "强毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "阵雪",
    80: "阵雨",
    81: "强阵雨",
    82: "暴雨",
    85: "阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴冰雹",
    99: "强雷暴伴冰雹",
}


class BeijingWeatherService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cached: dict[str, Any] | None = None
        self._cached_at = 0.0

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if self._cached and now - self._cached_at < CACHE_SECONDS:
                return {**self._cached, "cached": True}

        try:
            payload = httpx.get(BEIJING_FORECAST_URL, timeout=5.0).json()
            current = payload.get("current") or {}
            weather = self._normalize(current)
            with self._lock:
                self._cached = weather
                self._cached_at = now
            return {**weather, "cached": False}
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                if self._cached:
                    return {**self._cached, "cached": True, "stale": True}
            return {
                "city": "北京",
                "available": False,
                "message": f"天气服务暂不可用：{exc}",
                "driving_advice": "请结合现场路况谨慎驾驶。",
                "travel_advice": "请留意当地天气预警与交通信息。",
            }

    def _normalize(self, current: dict[str, Any]) -> dict[str, Any]:
        code = int(current.get("weather_code", -1))
        precipitation = float(current.get("precipitation", 0) or 0)
        snowfall = float(current.get("snowfall", 0) or 0)
        wind_speed = float(current.get("wind_speed_10m", 0) or 0)
        visibility = float(current.get("visibility", 10000) or 10000)
        temperature = float(current.get("temperature_2m", 0) or 0)
        driving_advice, travel_advice, level = self._advice(
            code, precipitation, snowfall, wind_speed, visibility, temperature
        )
        return {
            "city": "北京",
            "available": True,
            "observed_at": current.get("time"),
            "condition": WMO_TEXT.get(code, "天气变化"),
            "weather_code": code,
            "temperature_c": round(temperature, 1),
            "feels_like_c": round(float(current.get("apparent_temperature", temperature) or temperature), 1),
            "humidity_percent": int(current.get("relative_humidity_2m", 0) or 0),
            "precipitation_mm": round(precipitation, 1),
            "wind_speed_kmh": round(wind_speed, 1),
            "visibility_m": int(visibility),
            "driving_advice": driving_advice,
            "travel_advice": travel_advice,
            "advice_level": level,
        }

    @staticmethod
    def _advice(
        code: int,
        precipitation: float,
        snowfall: float,
        wind_speed: float,
        visibility: float,
        temperature: float,
    ) -> tuple[str, str, str]:
        if code >= 95 or visibility < 1000:
            return (
                "强对流或低能见度天气，建议非必要不驾车；必须出行请开启灯光、显著降速并增大车距。",
                "建议调整出行计划，优先选择安全的室内等待或公共交通。",
                "critical",
            )
        if snowfall > 0 or 71 <= code <= 86 or temperature <= 0:
            return (
                "注意结冰与湿滑路面，避免急加速、急刹车和急转向，预留更长制动距离。",
                "注意保暖与防滑，尽量避开桥面、坡道等易结冰路段。",
                "warning",
            )
        if precipitation >= 0.1 or 51 <= code <= 67:
            return (
                "雨天路面湿滑，请降低车速、打开近光灯，并与前车保持至少平时两倍车距。",
                "建议携带雨具，步行通过路口时注意车辆制动距离。",
                "warning",
            )
        if wind_speed >= 35:
            return (
                "风力较大，经过高架、桥梁和开阔路段时应双手稳握方向盘并谨慎超车。",
                "注意高空坠物和临时围挡，骑行请适当减速。",
                "warning",
            )
        if temperature >= 35:
            return (
                "高温天气注意车辆胎压与发动机散热，避免长时间怠速和疲劳驾驶。",
                "建议避开午后高温时段，及时补水并做好防晒。",
                "info",
            )
        return (
            "当前天气适宜驾驶，仍请遵守限速并保持注意力。",
            "当前天气适宜出行，过街时请遵守信号并留意车辆。",
            "info",
        )


beijing_weather_service = BeijingWeatherService()
