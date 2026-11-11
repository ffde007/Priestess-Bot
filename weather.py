"""Weather lookups through Open-Meteo (open-meteo.com): free, no API key."""

from __future__ import annotations

import re
from typing import Any

import aiohttp

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes.
WEATHER_CODES = {
    0: "晴", 1: "大部晴朗", 2: "多云", 3: "阴",
    45: "雾", 48: "冻雾",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨", 56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "小阵雨", 81: "阵雨", 82: "强阵雨", 85: "阵雪", 86: "强阵雪",
    95: "雷暴", 96: "雷暴伴小冰雹", 99: "雷暴伴大冰雹",
}


class WeatherError(Exception):
    pass


async def _geocode(session: aiohttp.ClientSession, location: str) -> dict[str, Any]:
    # "北京市" finds nothing but "北京" does; "Paris, France" needs just "Paris".
    candidates = [location, re.sub(r"[市县区省州]$", "", location), location.split(",")[0].split("，")[0]]
    for name in dict.fromkeys(c.strip() for c in candidates if c.strip()):
        params = {"name": name, "count": 1, "language": "zh", "format": "json"}
        async with session.get(GEOCODE_URL, params=params) as resp:
            data = await resp.json(content_type=None)
        if data.get("results"):
            return data["results"][0]
    raise WeatherError(f"找不到「{location}」这个地方")


async def get_weather(session: aiohttp.ClientSession, location: str, days: int = 1) -> str:
    """Current weather and a short daily forecast for a place, as plain text for the model."""
    days = max(1, min(7, days))
    try:
        place = await _geocode(session, location)
        params = {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,precipitation",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": days,
        }
        async with session.get(FORECAST_URL, params=params) as resp:
            data = await resp.json(content_type=None)
    except aiohttp.ClientError as e:
        raise WeatherError(f"天气服务连不上（{e.__class__.__name__}）") from e
    if "current" not in data:
        raise WeatherError(data.get("reason") or "天气服务没有返回数据")

    name = "，".join(p for p in (place.get("name"), place.get("admin1"), place.get("country")) if p)
    c = data["current"]
    lines = [
        f"{name}（当地时间 {c['time'].replace('T', ' ')}）：{WEATHER_CODES.get(c['weather_code'], '未知')}，"
        f"气温 {c['temperature_2m']}°C，体感 {c['apparent_temperature']}°C，湿度 {c['relative_humidity_2m']}%，"
        f"风速 {c['wind_speed_10m']} km/h，降水 {c['precipitation']} mm。"
    ]
    d = data.get("daily") or {}
    for i, date in enumerate(d.get("time") or []):
        rain = (d.get("precipitation_probability_max") or [None] * (i + 1))[i]
        lines.append(
            f"{date}：{WEATHER_CODES.get(d['weather_code'][i], '未知')}，"
            f"{d['temperature_2m_min'][i]}~{d['temperature_2m_max'][i]}°C"
            + (f"，降水概率 {rain}%" if rain is not None else "")
        )
    return "\n".join(lines)
