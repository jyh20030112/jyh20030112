import json
import os
import pathlib
import re
import httpx
from datetime import datetime, timezone, timedelta
from collections import Counter
from PIL import Image, ImageDraw, ImageFont

GITHUB_USERNAME = "jyh20030112"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
ASSETS_DIR = pathlib.Path("assets")

HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "GitHub-Profile-Stats",
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

TIME_PERIODS = {
    "morning": (6, 12),
    "afternoon": (12, 18),
    "evening": (18, 24),
    "night": (0, 6),
}

WEEKDAY_NAMES_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

PERIOD_COLORS = {
    "morning": "#FFB74D",
    "afternoon": "#FF8A65",
    "evening": "#9575CD",
    "night": "#4FC3F7",
}

PERIOD_LABELS = {
    "morning": "上午 (06-12)",
    "afternoon": "下午 (12-18)",
    "evening": "傍晚 (18-24)",
    "night": "深夜 (00-06)",
}

PERIOD_ORDER = ["morning", "afternoon", "evening", "night"]

DAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

DAY_COLORS = [
    "#FF6B6B", "#FFD93D", "#6BCB77", "#4D96FF",
    "#9B59B6", "#FF8C42", "#36C9C6",
]

LANG_COLORS = [
    "#3572A5", "#DA5B0B", "#E34C26", "#563D7C", "#2B7489",
    "#F7DF1E", "#41B883", "#DE3423", "#F18E33", "#178600",
    "#555555", "#438EFF", "#FF6F00", "#FFD43B", "#3776AB",
]

W = 800
PAD_LEFT = 155
PAD_RIGHT = 20
BAR_AREA_MAX = W - PAD_LEFT - PAD_RIGHT

TITLE_Y = 18
FIRST_BAR_Y = 68
ROW_H = 50
BAR_H = 28
BAR_Y_OFF = 14

IMG_BG = (13, 17, 23)
TITLE_RGB = (88, 166, 255)
LABEL_RGB = (230, 237, 243)
TEXT_RGB = (201, 209, 217)


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _find_font():
    system = __import__("platform").system()
    candidates = []
    if system == "Darwin":
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
        ]
    elif system == "Linux":
        candidates = [
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        ]
    else:
        candidates = [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
        ]

    for fp in candidates:
        try:
            return ImageFont.truetype(fp, 15), ImageFont.truetype(fp, 17, encoding="unic")
        except Exception:
            continue

    return ImageFont.load_default(), ImageFont.load_default()


FONT_SMALL, FONT_TITLE = _find_font()
print(f"Font loaded")


def _make_chart(title, items, total):
    n = len(items)
    h = FIRST_BAR_Y + n * ROW_H + 10
    img = Image.new("RGBA", (W, h), IMG_BG)
    draw = ImageDraw.Draw(img)

    draw.text((20, TITLE_Y), title, fill=TITLE_RGB, font=FONT_TITLE)

    for i, (label, value, color_hex) in enumerate(items):
        y = FIRST_BAR_Y + i * ROW_H
        pct = (value / total * 100) if total > 0 else 0
        bar_w = max(int(BAR_AREA_MAX * value / total), 0) if total > 0 else 0

        draw.text((10, y + 2), label, fill=LABEL_RGB, font=FONT_SMALL)

        if bar_w > 0:
            rgb = _hex_to_rgb(color_hex)
            draw.rounded_rectangle(
                (PAD_LEFT, y + BAR_Y_OFF, PAD_LEFT + bar_w, y + BAR_Y_OFF + BAR_H),
                radius=4, fill=rgb,
            )

        label_str = f"{int(value)}次 Push    {pct:.1f}%"
        tx = PAD_LEFT + bar_w + 8 if bar_w < 300 else PAD_LEFT + 8
        bbox = draw.textbbox((0, 0), label_str, font=FONT_SMALL)
        tw = bbox[2] - bbox[0]
        if tx + tw > W - 6:
            tx = W - tw - 6
        draw.text((tx, y + 2), label_str, fill=TEXT_RGB, font=FONT_SMALL)

    return img


def fetch_events():
    events = []
    for page in range(1, 6):
        url = f"https://api.github.com/users/{GITHUB_USERNAME}/events?per_page=100&page={page}"
        resp = httpx.get(url, headers=HEADERS, timeout=30.0)
        if resp.status_code != 200:
            break
        data = resp.json()
        if not data:
            break
        push_events = [e for e in data if e.get("type") == "PushEvent"]
        events.extend(push_events)
        if len(data) < 100:
            break
    print(f"Fetched {len(events)} push events")
    return events


def classify_time_period(hour):
    for period, (start, end) in TIME_PERIODS.items():
        if start <= hour < end:
            return period
    return "night"


def fetch_repo_languages(repo_name):
    url = f"https://api.github.com/repos/{repo_name}/languages"
    resp = httpx.get(url, headers=HEADERS, timeout=30.0)
    if resp.status_code == 200:
        data = resp.json()
        if data:
            primary_lang = max(data, key=data.get)
            return primary_lang, data
    return "Unknown", {}


def create_time_distribution_chart(period_counter):
    total = sum(period_counter.values())
    if total == 0:
        total = 1
    items = [(PERIOD_LABELS[p], period_counter.get(p, 0), PERIOD_COLORS[p]) for p in PERIOD_ORDER]
    img = _make_chart("Push 时间段分布", items, total)
    img.save(ASSETS_DIR / "time_distribution.png")
    print(f"Time distribution saved: {dict(period_counter)}")


def create_weekday_chart(day_counter):
    total = sum(day_counter.values())
    if total == 0:
        total = 1
    items = [(DAY_LABELS[i], day_counter.get(i, 0), DAY_COLORS[i]) for i in range(7)]
    img = _make_chart("星期几最活跃", items, total)
    img.save(ASSETS_DIR / "weekday_distribution.png")
    print(f"Weekday distribution saved: {dict(day_counter)}")


def create_language_chart(lang_counter):
    if not lang_counter:
        h = 120
        img = Image.new("RGBA", (W, h), IMG_BG)
        draw = ImageDraw.Draw(img)
        draw.text((20, TITLE_Y), "编程语言分布", fill=TITLE_RGB, font=FONT_TITLE)
        draw.text((W // 2, 72), "暂无数据", fill=TEXT_RGB, font=FONT_SMALL, anchor="mt")
        img.save(ASSETS_DIR / "language_distribution.png")
        return

    sorted_langs = sorted(lang_counter.items(), key=lambda x: x[1], reverse=True)[:10]
    total = sum(v for _, v in sorted_langs)
    items = [(lang, count, LANG_COLORS[i % len(LANG_COLORS)]) for i, (lang, count) in enumerate(sorted_langs)]
    img = _make_chart("编程语言分布", items, total)
    img.save(ASSETS_DIR / "language_distribution.png")
    print(f"Language distribution saved: {dict(lang_counter)}")


def generate_readme(period_counter, day_counter, lang_counter, total_pushes):
    total = sum(period_counter.values())
    peak_period = max(period_counter, key=period_counter.get) if total > 0 else "暂无"
    peak_period_cn = {
        "morning": "上午 🌅",
        "afternoon": "下午 ☀️",
        "evening": "傍晚 🌆",
        "night": "深夜 🌙",
    }

    peak_day_idx = max(day_counter, key=day_counter.get) if day_counter else 0
    peak_day = WEEKDAY_NAMES_CN[peak_day_idx] if day_counter else "暂无"

    peak_lang = max(lang_counter, key=lang_counter.get) if lang_counter else "暂无"

    readme = f"""# 👋 嗨，我是 jyh20030112

> 📊 以下数据由 GitHub Actions 自动更新 | 最后更新: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

---

## 📈 我的编码活动统计

基于最近 {total_pushes} 次 Push 记录：

| 🕐 最活跃时段 | 📆 最活跃星期 | 💻 最常用语言 |
|:---:|:---:|:---:|
| {peak_period_cn.get(peak_period, peak_period)} | {peak_day} | {peak_lang} |

---

### 🕐 Push 时间段分布
<p align="center">
  <img src="./assets/time_distribution.png" alt="时间段分布" width="520"/>
</p>

### 📆 星期几最活跃
<p align="center">
  <img src="./assets/weekday_distribution.png" alt="星期分布" width="600"/>
</p>

### 💻 编程语言分布
<p align="center">
  <img src="./assets/language_distribution.png" alt="语言分布" width="520"/>
</p>

---

<details>
<summary>🤖 关于这些统计</summary>
<br>
这些图表通过 GitHub Actions 自动生成，每天定时更新。统计基于我最近的公开 Push 事件。
</details>
"""
    return readme


def main():
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 50)
    print("  GitHub Profile Stats Generator")
    print("=" * 50)

    print("\n[1/4] 获取 Push 事件...")
    events = fetch_events()

    if not events:
        print("No push events found, generating empty charts...")

    period_counter = Counter()
    day_counter = Counter()
    lang_counter = Counter()
    repo_lang_cache = {}

    print(f"\n[2/4] 分析 {len(events)} 个 Push 事件...")
    for i, event in enumerate(events):
        created_at = event.get("created_at")
        if not created_at:
            continue

        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        bj_time = dt + timedelta(hours=8)
        hour = bj_time.hour
        weekday = bj_time.weekday()

        period = classify_time_period(hour)
        period_counter[period] += 1
        day_counter[weekday] += 1

        repo_name = event.get("repo", {}).get("name", "")
        if repo_name and repo_name not in repo_lang_cache:
            primary_lang, _ = fetch_repo_languages(repo_name)
            repo_lang_cache[repo_name] = primary_lang

        lang = repo_lang_cache.get(repo_name, "Unknown")
        if lang and lang != "Unknown":
            lang_counter[lang] += 1

        if (i + 1) % 50 == 0:
            print(f"  已处理 {i + 1}/{len(events)} 个事件...")

    total_pushes = len(events)
    print(f"\n  分析完成! 总计 {total_pushes} 次 Push")

    print("\n[3/4] 生成图表...")
    create_time_distribution_chart(period_counter)
    create_weekday_chart(day_counter)
    create_language_chart(lang_counter)

    print("\n[4/4] 更新 README.md...")
    readme_content = generate_readme(period_counter, day_counter, lang_counter, total_pushes)
    readme_path = pathlib.Path("README.md")
    readme_path.write_text(readme_content, encoding="utf-8")
    print("  README.md 已更新!")

    print("\n" + "=" * 50)
    print("  完成! 所有图表已生成。")
    print("=" * 50)


if __name__ == "__main__":
    main()
