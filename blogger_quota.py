"""Publish cooldown, daily caps, and category mix quotas."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE_PATH = Path(".blogger_quota_state.json")

# Defaults tuned for low early traffic (~3 PV/post).
DEFAULT_MIN_INTERVAL_MINUTES = int(os.environ.get("BLOGGER_MIN_INTERVAL_MINUTES", "240"))
DEFAULT_MAX_PER_DAY = int(os.environ.get("BLOGGER_MAX_NEW_POSTS_PER_DAY", "6"))
DEFAULT_MAX_PER_RUN = int(os.environ.get("BLOGGER_MAX_POSTS_PER_RUN", "1"))

# Daily category caps (sports blocked elsewhere).
DAILY_CATEGORY_CAPS = {
    "sports_ent": 0,
    "finance": int(os.environ.get("BLOGGER_DAILY_CAP_FINANCE", "2")),
    "guide": int(os.environ.get("BLOGGER_DAILY_CAP_GUIDE", "3")),
    "it": int(os.environ.get("BLOGGER_DAILY_CAP_IT", "2")),
    "society": int(os.environ.get("BLOGGER_DAILY_CAP_SOCIETY", "2")),
    "other": int(os.environ.get("BLOGGER_DAILY_CAP_OTHER", "1")),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_state(path: Path = STATE_PATH) -> dict:
    if not path.exists():
        return {
            "last_publish_at": None,
            "publishes": [],  # [{ts, category, title, url}]
            "inserts_today": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _today_key(now: datetime | None = None) -> str:
    now = now or _now()
    # KST day boundary for operator mental model
    kst = now + timedelta(hours=9)
    return kst.strftime("%Y-%m-%d")


def recent_publishes_today(state: dict) -> list[dict]:
    key = _today_key()
    out = []
    for item in state.get("publishes") or []:
        ts = item.get("ts")
        if not ts:
            continue
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if _today_key(dt) == key:
            out.append(item)
    return out


def can_publish(category: str, state: dict | None = None) -> tuple[bool, str]:
    state = state if state is not None else load_state()
    now = _now()

    last = state.get("last_publish_at")
    if last:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        delta = now - last_dt
        need = timedelta(minutes=DEFAULT_MIN_INTERVAL_MINUTES)
        if delta < need:
            remain = int((need - delta).total_seconds() // 60) + 1
            return False, f"cooldown active: wait ~{remain} more minutes"

    today = recent_publishes_today(state)
    if len(today) >= DEFAULT_MAX_PER_DAY:
        return False, f"daily cap reached ({DEFAULT_MAX_PER_DAY})"

    cap = DAILY_CATEGORY_CAPS.get(category, 1)
    cat_count = sum(1 for x in today if x.get("category") == category)
    if cat_count >= cap:
        return False, f"category cap reached for {category} ({cap}/day)"

    return True, "ok"


def record_publish(
    *,
    category: str,
    title: str,
    url: str,
    post_id: str = "",
    state: dict | None = None,
    path: Path = STATE_PATH,
) -> dict:
    state = state if state is not None else load_state()
    now = _now().isoformat()
    state["last_publish_at"] = now
    pubs = state.setdefault("publishes", [])
    pubs.append(
        {
            "ts": now,
            "category": category,
            "title": title,
            "url": url,
            "post_id": post_id,
        }
    )
    # keep last 200
    state["publishes"] = pubs[-200:]
    day = _today_key()
    inserts = state.setdefault("inserts_today", {})
    inserts[day] = int(inserts.get(day) or 0) + 1
    save_state(state, path)
    return state
