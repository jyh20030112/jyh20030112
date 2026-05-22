import json
import os
import pathlib
import re
import httpx
from datetime import datetime, timezone, timedelta
from collections import Counter

GITHUB_USERNAME = "jyh20030112"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

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

PERIOD_EMOJI = {
    "morning": "🌞",
    "afternoon": "☀",
    "evening": "🌆",
    "night": "🌙",
}

PERIOD_LABELS = {
    "morning": "上午 (06-12)",
    "afternoon": "下午 (12-18)",
    "evening": "傍晚 (18-24)",
    "night": "深夜 (00-06)",
}

PERIOD_ORDER = ["morning", "afternoon", "evening", "night"]

DAY_EMOJI = ["🐔", "🐱", "🐶", "🐮", "🐯", "🐰", "🐲"]

DAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


ZERO_WIDTH_CHARS = {
    "\ufe0f", "\ufe0e",
}


def _visual_width(s):
    w = 0
    for ch in str(s):
        if ch in ZERO_WIDTH_CHARS:
            continue
        if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f' or '\uff00' <= ch <= '\uffef':
            w += 2
        elif ord(ch) > 127:
            w += 2
        else:
            w += 1
    return w


def _pad_visual(s, target_width):
    cur = _visual_width(s)
    if cur >= target_width:
        return s + " "
    return s + " " * (target_width - cur)


def _make_text_bar(items, total, bar_width=25):
    label_w = max(_visual_width(label) for label, _ in items) + 2
    val_w = 12

    lines = []
    for label, value in items:
        pct = (value / total * 100) if total > 0 else 0.0
        filled = int(bar_width * value / total) if total > 0 else 0
        empty = bar_width - filled
        bar = "█" * filled + "░" * empty
        val_str = f"{int(value)}次 Push".rjust(10)
        pct_str = f"{pct:5.1f} %"

        label_part = _pad_visual(label, label_w)
        val_part = _pad_visual(val_str, val_w)
        lines.append(f"{label_part} {val_part} {bar}  {pct_str}")

    chart = "\n".join(lines)
    return f"```text\n{chart}\n```"


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
    total = max(sum(period_counter.values()), 1)
    items = [
        (f"{PERIOD_EMOJI[p]} {PERIOD_LABELS[p]}", period_counter.get(p, 0))
        for p in PERIOD_ORDER
    ]
    return _make_text_bar(items, total)


def create_weekday_chart(day_counter):
    total = max(sum(day_counter.values()), 1)
    items = [
        (f"{DAY_EMOJI[i]} {DAY_LABELS[i]}", day_counter.get(i, 0))
        for i in range(7)
    ]
    return _make_text_bar(items, total)


def create_language_chart(lang_counter):
    if not lang_counter:
        return "暂无数据"

    sorted_langs = sorted(lang_counter.items(), key=lambda x: x[1], reverse=True)[:10]
    total = sum(v for _, v in sorted_langs)
    items = [(f"💻 {lang}", count) for lang, count in sorted_langs]
    return _make_text_bar(items, total)


def generate_readme(period_counter, day_counter, lang_counter, total_pushes,
                     period_chart, weekday_chart, lang_chart):
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

    readme = f"""# 👋 嗨，我是 蛋烧肉粽

> 📊 以下数据由 GitHub Actions 自动更新 | 最后更新: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

---

## 📈 我的编码活动统计

基于最近 {total_pushes} 次 Push 记录：

| 🕐 最活跃时段 | 📆 最活跃星期 | 💻 最常用语言 |
|:---:|:---:|:---:|
| {peak_period_cn.get(peak_period, peak_period)} | {peak_day} | {peak_lang} |

---

### 🕐 Push 时间段分布

{period_chart}

### 📆 星期几最活跃

{weekday_chart}

### 💻 编程语言分布

{lang_chart}

---

<details>
<summary>🤖 关于这些统计</summary>
<br>

这些数据由 GitHub Actions 每 6 小时自动更新。
统计基于我最近的公开 Push 事件，
通过 Unicode 文本条形图直接渲染，无需加载外部图片。

</details>
"""
    return readme


def main():
    print("=" * 50)
    print("  GitHub Profile Stats Generator")
    print("=" * 50)

    print("\n[1/3] 获取 Push 事件...")
    events = fetch_events()

    period_counter = Counter()
    day_counter = Counter()
    lang_counter = Counter()
    repo_lang_cache = {}

    print(f"\n[2/3] 分析 {len(events)} 个 Push 事件...")
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

    print("\n[3/3] 生成 README.md...")
    period_chart = create_time_distribution_chart(period_counter)
    weekday_chart = create_weekday_chart(day_counter)
    lang_chart = create_language_chart(lang_counter)

    readme_content = generate_readme(
        period_counter, day_counter, lang_counter,
        total_pushes, period_chart, weekday_chart, lang_chart,
    )

    readme_path = pathlib.Path("README.md")
    readme_path.write_text(readme_content, encoding="utf-8")
    print("  README.md 已更新!")

    print("\n" + "=" * 50)
    print("  完成!  README 已包含文本柱状图。")
    print("=" * 50)


if __name__ == "__main__":
    main()
