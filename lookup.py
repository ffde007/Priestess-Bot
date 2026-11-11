"""Live product prices, image lookup, places and directions, through SerpApi (serp.py).

Google Shopping (prices across stores), Google Lens (what's in a picture and where it's from),
Google Maps (places, ratings, opening hours) and Google Maps directions. Each result is trimmed
to a few lines for the model, with a link to see more. Text on the "avoid" word list is dropped.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

import moderation
import serp

PRODUCTS_SHOWN = 6
MATCHES_SHOWN = 6
PLACES_SHOWN = 6
ROUTES_SHOWN = 3
SHOPPING_SORT = {"price_low": 1, "price_high": 2}
TRAVEL_MODES = {"best": 6, "driving": 0, "transit": 3, "walking": 2, "cycling": 1}


def _ok(text: str) -> bool:
    return moderation.check(text, kinds=("avoid",)) is None


# ---- Google Shopping ----------------------------------------------------------


async def find_products(query: str, max_price: int = 0, sort: str = "relevance") -> str:
    params: dict = {"engine": "google_shopping", "q": query, "hl": "en", "gl": "us"}
    if max_price > 0:
        params["max_price"] = max_price
    if sort in SHOPPING_SORT:
        params["sort_by"] = SHOPPING_SORT[sort]
    data = await serp.search(params)
    rows = []
    for p in data.get("shopping_results") or []:
        if not p.get("price") or not _ok(p.get("title") or ""):
            continue
        line = f"{p.get('title')} · {p['price']} · {p.get('source') or '?'}"
        if p.get("multiple_sources"):
            line += "（还有其他店）"
        if p.get("rating"):
            line += f" · {p['rating']}/5（{p.get('reviews', 0)} 条评价）"
        if p.get("delivery"):
            line += f" · {p['delivery']}"
        if p.get("product_link"):
            line += f" · {p['product_link'].replace(' ', '%20')}"
        rows.append(line)
        if len(rows) == PRODUCTS_SHOWN:
            break
    link = "https://www.google.com/search?tbm=shop&" + urlencode({"q": query})
    if not rows:
        return f"Google Shopping 上没有找到「{query}」。可以给对方这个链接自己看：{link}"
    return (
        f"Google Shopping 实时价格：「{query}」，美元（商店自己标的价格，可能不含税和运费）。"
        "同一商品在不同店、不同容量或版本的价格都可能列出，回答时注意看清标题。\n"
        + "\n".join(f"{i}. {r}" for i, r in enumerate(rows, 1))
        + f"\n更多结果：{link}"
    )


# ---- Google Lens --------------------------------------------------------------


async def look_at_image(url: str, question: str = "") -> str:
    params: dict = {"engine": "google_lens", "url": url, "type": "all", "hl": "zh-cn", "country": "us"}
    if question.strip():
        params["q"] = question.strip()[:100]
    data = await serp.search(params)
    parts = []
    related = [r.get("query") for r in data.get("related_content") or [] if r.get("query") and _ok(r["query"])]
    if related:
        parts.append("Google 认为图里可能是：" + "、".join(related[:5]))
    matches, seen = [], set()
    for m in data.get("visual_matches") or []:
        title = m.get("title") or ""
        if not title or title in seen or not _ok(title):
            continue
        seen.add(title)
        line = f"{title}（{m.get('source') or '?'}）"
        price = m.get("price")
        if isinstance(price, dict) and price.get("value"):
            line += f" · {price['value']}"
        if m.get("link"):
            line += f" · {m['link']}"
        matches.append(line)
        if len(matches) == MATCHES_SHOWN:
            break
    if matches:
        parts.append("长得像的网上图片（标题和来源）：\n" + "\n".join(f"{i}. {m}" for i, m in enumerate(matches, 1)))
    pages = [
        f"{o.get('title')}（{o.get('source') or o.get('displayed_link') or '?'}）：{(o.get('snippet') or '')[:150]}"
        for o in (data.get("organic_results") or [])[:3]
        if o.get("title") and _ok(f"{o.get('title')} {o.get('snippet') or ''}")
    ]
    if pages:
        parts.append("相关网页：\n" + "\n".join(pages))
    if not parts:
        return "Google Lens 没有认出这张图里的东西。"
    return (
        "Google Lens 识图结果（这是网上相似图片的标题，不是你亲眼看到的；根据它们推断图里是什么，拿不准就说可能）：\n"
        + "\n\n".join(parts)
    )


# ---- Google Maps --------------------------------------------------------------


def _hours_today(place: dict) -> str:
    if place.get("open_state"):
        return place["open_state"]
    return place.get("hours") or ""


async def find_places(query: str, location: str = "", open_now: bool = False, min_rating: float = 0) -> str:
    q = f"{query} {location}".strip() if location and location.lower() not in query.lower() else query
    params: dict = {"engine": "google_maps", "type": "search", "q": q, "hl": "en", "gl": "us"}
    if open_now:
        params["open_state"] = "now"
    if min_rating >= 2:
        params["min_rating"] = min(4.5, round(min_rating * 2) / 2)
    data = await serp.search(params)
    places = data.get("local_results") or []
    if not places and data.get("place_results"):
        places = [data["place_results"]]
    rows = []
    for p in places:
        if not p.get("title") or not _ok(p["title"]):
            continue
        line = p["title"]
        if p.get("rating"):
            line += f" · {p['rating']}/5（{p.get('reviews', 0)} 条评价）"
        if p.get("price"):
            line += f" · {p['price']}"
        if p.get("type"):
            line += f" · {p['type']}"
        if p.get("address"):
            line += f" · {p['address']}"
        if hours := _hours_today(p):
            line += f" · {hours}"
        if p.get("phone"):
            line += f" · {p['phone']}"
        if p.get("place_id"):
            line += f" · https://www.google.com/maps/place/?q=place_id:{p['place_id']}"
        rows.append(line)
        if len(rows) == PLACES_SHOWN:
            break
    link = "https://www.google.com/maps/search/" + quote(q)
    if not rows:
        return f"Google Maps 上没有找到「{q}」。可以给对方这个链接：{link}"
    return (
        f"Google Maps 实时结果：「{q}」（营业状态是当地此刻的）：\n"
        + "\n".join(f"{i}. {r}" for i, r in enumerate(rows, 1))
        + f"\n在地图上看全部：{link}"
    )


async def get_directions(start: str, end: str, mode: str = "best") -> str:
    params = {
        "engine": "google_maps_directions",
        "start_addr": start,
        "end_addr": end,
        "travel_mode": TRAVEL_MODES.get(mode, 6),
        "hl": "en",
        "gl": "us",
        "distance_unit": 0,
    }
    data = await serp.search(params)
    routes = (data.get("directions") or [])[:ROUTES_SHOWN]
    link = "https://www.google.com/maps/dir/?" + urlencode(
        {"api": 1, "origin": start, "destination": end, "travelmode": {"best": "", "driving": "driving",
         "transit": "transit", "walking": "walking", "cycling": "bicycling"}.get(mode, "")}
    )
    if not routes:
        return f"Google Maps 没有找到从「{start}」到「{end}」的路线。可以给对方这个链接：{link}"
    rows = []
    for r in routes:
        line = f"{r.get('travel_mode', '?')}：{r.get('formatted_duration', '?')}，{r.get('formatted_distance', '?')}"
        if r.get("via"):
            line += f"，经 {r['via']}"
        if typical := r.get("typical_duration_range"):
            line += f"（平时 {typical}）"
        legs = [t.get("title") for t in r.get("trips") or [] if t.get("title")]
        if legs and r.get("travel_mode") == "Transit":
            line += "；换乘：" + " → ".join(legs[:6])
        rows.append(line)
    return (
        f"Google Maps 路线：「{start}」→「{end}」（按此刻的路况）：\n"
        + "\n".join(f"{i}. {r}" for i, r in enumerate(rows, 1))
        + f"\n在地图上看：{link}"
    )
