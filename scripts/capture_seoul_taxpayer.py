#!/usr/bin/env python3
"""Capture Seoul model-taxpayer page screenshots via Chrome CDP."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from PIL import Image

OUT_DIR = Path("/workspace/posts/images/seoul-model-taxpayer")
USER_DATA = Path("/tmp/chrome-seoul")
URL = "https://news.seoul.go.kr/gov/archives/200152"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    USER_DATA.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pkill", "-f", "remote-debugging-port=9222"], capture_output=True)
    time.sleep(0.5)

    proc = subprocess.Popen(
        [
            "google-chrome",
            "--headless=new",
            "--disable-gpu",
            "--remote-debugging-port=9222",
            "--remote-allow-origins=*",
            f"--user-data-dir={USER_DATA}",
            "--window-size=1280,900",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2.5)

    try:
        import websocket
    except ImportError:
        subprocess.check_call(["pip", "install", "-q", "websocket-client"])
        import websocket

    with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=10) as resp:
        ws_url = json.load(resp)["webSocketDebuggerUrl"]

    ws = websocket.create_connection(ws_url, timeout=60)
    msg_id = 0

    def send(method, params=None, session_id=None):
        nonlocal msg_id
        msg_id += 1
        payload = {"id": msg_id, "method": method}
        if params:
            payload["params"] = params
        if session_id:
            payload["sessionId"] = session_id
        ws.send(json.dumps(payload))
        while True:
            data = json.loads(ws.recv())
            if data.get("id") == msg_id:
                return data

    res = send("Target.createTarget", {"url": "about:blank"})
    target_id = res["result"]["targetId"]
    res = send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
    sid = res["result"]["sessionId"]

    def ssend(method, params=None):
        return send(method, params, session_id=sid)

    ssend("Page.enable")
    ssend("Runtime.enable")
    ssend("Page.navigate", {"url": URL})
    for i in range(50):
        time.sleep(0.4)
        r = ssend("Runtime.evaluate", {"expression": "document.readyState"})
        state = r.get("result", {}).get("result", {}).get("value")
        if state == "complete":
            print("ready at", i)
            break
    time.sleep(2.5)

    metrics = ssend("Page.getLayoutMetrics")
    content = metrics["result"]["cssContentSize"]
    height = int(min(content["height"], 14000))
    print("page height", height)

    ssend(
        "Emulation.setDeviceMetricsOverride",
        {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False},
    )
    shot = ssend(
        "Page.captureScreenshot",
        {
            "format": "png",
            "fromSurface": True,
            "captureBeyondViewport": True,
            "clip": {"x": 0, "y": 0, "width": 1280, "height": height, "scale": 1},
        },
    )
    png = base64.b64decode(shot["result"]["data"])
    full = OUT_DIR / "_full.png"
    full.write_bytes(png)
    print("saved full", len(png))

    im = Image.open(full)
    print("dims", im.size)
    w, h = im.size

    loc = ssend(
        "Runtime.evaluate",
        {
            "expression": """
(() => {
  const out = {};
  const texts = [
    ['summary', '지원혜택 요약'],
    ['shinhan', '신한은행 지원 내용'],
    ['woori', '우리은행 지원'],
    ['coffee', '커피빈 할인쿠폰'],
    ['medical', '의료기관 할인 지원'],
  ];
  for (const [k, t] of texts) {
    const el = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6,p,div,strong,b,th,td,span,li')]
      .find(e => (e.innerText||'').trim().includes(t) && (e.innerText||'').trim().length < 80);
    if (el) {
      const r = el.getBoundingClientRect();
      out[k] = {y: Math.round(r.top + window.scrollY)};
    }
  }
  return out;
})()
""",
            "returnByValue": True,
        },
    )
    positions = loc.get("result", {}).get("result", {}).get("value") or {}
    print("positions", positions)

    def y_of(key: str, default: int) -> int:
        return int(positions.get(key, {}).get("y", default))

    ys = y_of("summary", 1100)
    ys2 = y_of("shinhan", ys + 700)
    yw = y_of("woori", ys2 + 900)
    yc = y_of("coffee", yw + 700)
    ymed = y_of("medical", yc + 1200)

    def save_crop(name: str, y0: int, y1: int, x0: int = 60, x1: int = 1220) -> None:
        y0 = max(0, y0)
        y1 = min(h, y1)
        crop = im.crop((x0, y0, min(w, x1), y1)).convert("RGB")
        path = OUT_DIR / f"{name}.jpg"
        crop.save(path, quality=88, optimize=True)
        print("crop", name, crop.size, path.stat().st_size)

    save_crop("00-page-overview", max(0, ys - 80), ys + 620)
    save_crop("01-summary-benefits", max(0, ys - 40), ys + 580)
    save_crop("02-shinhan-support", ys2 - 40, ys2 + 850)
    save_crop("03-woori-credit", yw - 40, min(h, yc - 20))
    save_crop("04-culture-discount", yc - 40, min(h, ymed - 20))
    save_crop("05-medical-list", ymed - 40, min(h, ymed + 900))

    ws.close()
    proc.terminate()
    for p in sorted(OUT_DIR.glob("*.jpg")):
        print(p.name, p.stat().st_size)


if __name__ == "__main__":
    main()
