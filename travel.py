"""Live flight and hotel prices from Google Flights / Google Hotels, through SerpApi (serp.py).

Flights for given dates, the cheapest dates on a route (calendar), cheap destinations from an
airport (deals), and hotels. Results are trimmed to a few options and handed to the model as
plain text, with a link to the full Google page.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import serp
from serp import SerpError

log = logging.getLogger(__name__)

FLIGHTS_SHOWN = 6
HOTELS_SHOWN = 5
DATES_SHOWN = 8
DEALS_SHOWN = 8
STOPS = {True: 1, False: 0}  # nonstop only -> SerpApi "stops" value
HOTEL_SORT = {"price": 3, "rating": 8, "reviews": 13}
DEAL_LENGTHS = {"weekend": 2, "week": 1, "two_weeks": 3}
LOCALE = {"hl": "en", "gl": "us", "currency": "USD"}
TravelError = SerpError


async def _search(params: dict) -> dict:
    return await serp.search({**params, **LOCALE})


def codes(text: str) -> str:
    """"jfk, ewr" -> "JFK,EWR"; Google city ids (/m/...) keep their case."""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    return ",".join(p if p.startswith("/") else p.upper() for p in parts)


# ---- flights ------------------------------------------------------------------


def flights_link(origin: str, destination: str, depart: str, ret: str = "") -> str:
    """A Google Flights page for the same search (works without SerpApi too)."""
    q = f"Flights from {origin.split(',')[0]} to {destination.split(',')[0]} on {depart}"
    if ret:
        q += f" through {ret}"
    return "https://www.google.com/travel/flights?q=" + quote(q)


def _leg_line(option: dict) -> str:
    legs = option.get("flights") or []
    if not legs:
        return "?"
    first, last = legs[0], legs[-1]
    dep, arr = first.get("departure_airport") or {}, last.get("arrival_airport") or {}
    airlines = " / ".join(dict.fromkeys(leg.get("airline") or "?" for leg in legs))
    numbers = ", ".join(leg.get("flight_number") or "" for leg in legs if leg.get("flight_number"))
    layovers = option.get("layovers") or []
    stops = "直飞" if not layovers else f"经停 {len(layovers)} 次（" + "、".join(
        f"{lay.get('id') or lay.get('name')} {lay.get('duration', 0) // 60}小时{lay.get('duration', 0) % 60}分"
        + ("，过夜" if lay.get("overnight") else "") for lay in layovers
    ) + "）"
    minutes = option.get("total_duration") or 0
    return (
        f"${option.get('price', '?')} · {airlines}（{numbers}）· {dep.get('id')} {dep.get('time', '')[-5:]} → "
        f"{arr.get('id')} {arr.get('time', '')[-5:]}"
        f"{'（次日到达）' if dep.get('time', '')[:10] != arr.get('time', '')[:10] else ''} · "
        f"{minutes // 60}小时{minutes % 60}分 · {stops}"
    )


def describe_flights(data: dict, origin: str, destination: str, depart: str, ret: str) -> str:
    options = (data.get("best_flights") or []) + sorted(
        data.get("other_flights") or [], key=lambda o: o.get("price") or 10**9
    )
    seen, rows = set(), []
    for o in options:
        line = _leg_line(o)
        if line not in seen and o.get("price"):
            seen.add(line)
            rows.append(line)
        if len(rows) == FLIGHTS_SHOWN:
            break
    link = (data.get("search_metadata") or {}).get("google_flights_url") or flights_link(origin, destination, depart, ret)
    trip = f"{depart} 出发、{ret} 返回的往返" if ret else f"{depart} 的单程"
    if not rows:
        return f"Google Flights 上没有找到 {origin} → {destination} {trip}航班。可以给对方这个链接自己看：{link}"
    head = f"Google Flights 实时结果：{origin} → {destination}，{trip}，美元。"
    if ret:
        head += "价格是往返总价（按这班去程算），返程航班要在链接里选。"
    insight = data.get("price_insights") or {}
    if insight.get("lowest_price"):
        typical = insight.get("typical_price_range") or []
        head += f"\n最低价 ${insight['lowest_price']}，价格水平：{insight.get('price_level', '?')}"
        if len(typical) == 2:
            head += f"（这条航线平时 ${typical[0]}–${typical[1]}）"
    body = "\n".join(f"{i}. {row}" for i, row in enumerate(rows, 1))
    return f"{head}\n前几个选择（前面是 Google 推荐的，后面按价格）：\n{body}\n完整结果：{link}\n（价格以下单页面为准。）"


async def find_flights(origin: str, destination: str, depart: str, ret: str = "", adults: int = 1, nonstop: bool = False) -> str:
    params = {
        "engine": "google_flights",
        "departure_id": codes(origin),
        "arrival_id": codes(destination),
        "outbound_date": depart,
        "type": 1 if ret else 2,
        "adults": max(1, min(9, adults)),
        "stops": STOPS[nonstop],
    }
    if ret:
        params["return_date"] = ret
    data = await _search(params)
    return describe_flights(data, origin, destination, depart, ret)


# ---- hotels -------------------------------------------------------------------


def hotels_link(location: str) -> str:
    return "https://www.google.com/travel/hotels/" + quote(location)


def describe_hotels(data: dict, location: str, check_in: str, check_out: str) -> str:
    rows = []
    for p in data.get("properties") or []:
        night = (p.get("rate_per_night") or {}).get("lowest")
        if not night:
            continue
        total = (p.get("total_rate") or {}).get("lowest")
        rating = p.get("overall_rating")
        stars = p.get("hotel_class") or ""
        line = f"{p.get('name')}" + (f"（{stars}）" if stars else "") + f" · 每晚 {night}"
        if total:
            line += f"，共 {total}"
        if rating:
            line += f" · 评分 {rating}/5（{p.get('reviews', 0)} 条评价）"
        if p.get("link"):
            line += f" · {p['link']}"
        rows.append(line)
        if len(rows) == HOTELS_SHOWN:
            break
    link = (data.get("search_metadata") or {}).get("google_hotels_url") or hotels_link(location)
    if not rows:
        return f"Google Hotels 上没有找到「{location}」{check_in} 到 {check_out} 的可订酒店。可以给对方这个链接：{link}"
    body = "\n".join(f"{i}. {row}" for i, row in enumerate(rows, 1))
    return (
        f"Google Hotels 实时结果：「{location}」，{check_in} 入住、{check_out} 退房，美元，价格含税费。\n{body}\n"
        f"完整结果：{link}\n（价格以预订页面为准。）"
    )


async def find_hotels(
    location: str, check_in: str, check_out: str, adults: int = 2, sort: str = "relevance", max_price: int = 0
) -> str:
    params = {
        "engine": "google_hotels",
        "q": location,
        "check_in_date": check_in,
        "check_out_date": check_out,
        "adults": max(1, min(9, adults)),
    }
    if sort in HOTEL_SORT:
        params["sort_by"] = HOTEL_SORT[sort]
    if max_price > 0:
        params["max_price"] = max_price
    data = await _search(params)
    return describe_hotels(data, location, check_in, check_out)


# ---- cheapest dates and destinations ------------------------------------------


async def find_flight_dates(origin: str, destination: str, start: str, end: str, trip_days: int = 7) -> str:
    """The cheapest days to fly a route between start and end (trip_days 0 = one way)."""
    params = {
        "engine": "google_flights_calendar",
        "departure_id": codes(origin).split(",")[0],  # the calendar takes one airport each way
        "arrival_id": codes(destination).split(",")[0],
        "date_range_start": start,
        "date_range_end": end,
        "type": 1 if trip_days > 0 else 2,
    }
    if trip_days > 0:
        params["round_trip_days"] = trip_days
    data = await _search(params)
    prices = [p for p in data.get("prices") or [] if p.get("price")]
    trip = f"往返（玩 {trip_days} 天）" if trip_days > 0 else "单程"
    if not prices:
        return f"Google Flights 没有给出 {origin} → {destination} 在 {start} 到 {end} 之间的{trip}价格。"
    cheapest = sorted(prices, key=lambda p: p["price"])[:DATES_SHOWN]
    rows = [
        f"{p['outbound_date']}" + (f" → {p['return_date']}" if p.get("return_date") else "") + f"：${p['price']}"
        for p in cheapest
    ]
    span = f"{min(p['price'] for p in prices)}–{max(p['price'] for p in prices)}"
    best = cheapest[0]
    link = flights_link(origin, destination, best["outbound_date"], best.get("return_date") or "")
    return (
        f"Google Flights 日历：{origin} → {destination}，{start} 到 {end} 之间出发的{trip}，美元。"
        f"这段时间价格在 ${span} 之间，最便宜的几天：\n" + "\n".join(rows)
        + f"\n最便宜那天的航班：{link}\n（日历价格是参考价，具体以选好航班后的价格为准。）"
    )


async def find_flight_deals(origin: str, length: str = "", dates: str = "", max_price: int = 0) -> str:
    """Cheap places to fly from an airport, with dates and prices (Google Flights deals)."""
    params: dict = {"engine": "google_flights_deals", "departure_id": codes(origin)}
    if length in DEAL_LENGTHS:
        params["travel_duration"] = DEAL_LENGTHS[length]
    if dates:
        params["outbound_date"] = dates
    if max_price > 0:
        params["max_price"] = max_price
    data = await _search(params)
    deals = (data.get("deals") or [])[:DEALS_SHOWN]
    if not deals:
        return f"Google Flights 没有找到从 {origin} 出发的特价机票。"
    rows = []
    for d in deals:
        line = f"{d.get('name')}（{d.get('country', '')}，{d.get('arrival_airport_code', '')}）：${d.get('price')}"
        if d.get("discount_percentage"):
            line += f"，比平时便宜 {d['discount_percentage']}%"
        out, back = d.get("outbound_date") or d.get("start_date") or "", d.get("return_date") or d.get("end_date") or ""
        line += f" · {out} → {back}"
        if d.get("airline"):
            line += f" · {d['airline']}"
        if d.get("stops") is not None:
            line += " · 直飞" if d["stops"] == 0 else f" · 经停 {d['stops']} 次"
        if d.get("arrival_airport_code") and out:
            line += f" · {flights_link(origin, d['arrival_airport_code'], out, back)}"
        rows.append(line)
    return f"Google Flights 特价：从 {origin} 出发的往返，美元。\n" + "\n".join(f"{i}. {r}" for i, r in enumerate(rows, 1))
