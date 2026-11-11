"""Daily chat counters: messages sent to the API, web searches and tokens, per person.

Kept in data/chat_usage.json by local date, so limits survive restarts and /聊天统计 and /余额
can show where the tokens went. Per-person detail is kept for KEEP_DAYS days; older days are
folded into one line of totals each and kept for good.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

USAGE_FILE = Path(__file__).parent / "data" / "chat_usage.json"
KEEP_DAYS = 7
USER_FIELDS = ("messages", "searches", "tasks", "input", "cache_read", "output")
DAY_FIELDS = ("messages", "blocked", "stickers", "quick")


def _day_totals(day: dict[str, Any]) -> dict[str, int]:
    if "totals" in day:  # an old, folded day
        return day["totals"]
    return {f: sum(u.get(f, 0) for u in day.get("users", {}).values()) for f in USER_FIELDS}


class Usage:
    def __init__(self, path: Path = USAGE_FILE) -> None:
        self.path = path
        try:
            self.days: dict[str, dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.days = {}

    def today(self) -> dict[str, Any]:
        key = date.today().isoformat()
        if key not in self.days:
            cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
            for k, day in self.days.items():
                if k < cutoff and "users" in day:
                    day["totals"] = _day_totals(day)
                    del day["users"]
            self.days[key] = {**{f: 0 for f in DAY_FIELDS}, "users": {}}
        return self.days[key]

    def user(self, user_id: int, name: str = "") -> dict[str, Any]:
        entry = self.today()["users"].setdefault(str(user_id), {**{f: 0 for f in USER_FIELDS}, "limited": False})
        if name:
            entry["name"] = name
        return entry

    def count(self, field: str, n: int = 1) -> None:
        self.today()[field] = self.today().get(field, 0) + n
        self.save()

    def totals(self, since: date | None = None) -> dict[str, int]:
        """Messages, searches and tokens summed from this day on (None = all recorded days)."""
        self.today()
        start = since.isoformat() if since else ""
        result = dict.fromkeys(USER_FIELDS, 0)
        for key, day in self.days.items():
            if key >= start:
                for field, n in _day_totals(day).items():
                    result[field] += n
        return result

    def first_day(self) -> str | None:
        return min(self.days, default=None)

    def save(self) -> None:
        try:
            self.path.parent.mkdir(exist_ok=True)
            self.path.write_text(json.dumps(self.days, ensure_ascii=False), encoding="utf-8")
        except OSError:
            log.exception("Couldn't save %s", self.path)
