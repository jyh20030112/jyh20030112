import json
import os
import pathlib
import re
import time
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
    "afternoon": "🌆",
    "evening": "🌃",
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


def _format_bytes(value):
    value = float(value)
    units = ["B", "KB", "MB", "GB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024


def _make_language_bar(items, total, bar_width=25):
    label_w = max(_visual_width(label) for label, _ in items) + 2
    val_w = 10

    lines = []
    for label, value in items:
        pct = (value / total * 100) if total > 0 else 0.0
        filled = int(bar_width * value / total) if total > 0 else 0
        empty = bar_width - filled
        bar = "█" * filled + "░" * empty
        val_str = _format_bytes(value).rjust(9)
        pct_str = f"{pct:5.1f} %"

        label_part = _pad_visual(label, label_w)
        val_part = _pad_visual(val_str, val_w)
        lines.append(f"{label_part} {val_part} {bar}  {pct_str}")

    chart = "\n".join(lines)
    return f"```text\n{chart}\n```"


def _get_with_retries(url, retries=3):
    for attempt in range(1, retries + 1):
        try:
            return httpx.get(url, headers=HEADERS, timeout=60.0)
        except httpx.HTTPError as exc:
            print(f"Warning: request failed ({attempt}/{retries}) for {url}: {exc}")
            if attempt < retries:
                time.sleep(attempt)
    return None


def fetch_events():
    events = []
    for page in range(1, 6):
        url = f"https://api.github.com/users/{GITHUB_USERNAME}/events?per_page=100&page={page}"
        resp = _get_with_retries(url)
        if resp is None:
            print("Warning: failed to fetch events")
            return None if not events else events
        if resp.status_code != 200:
            print(f"Warning: GitHub events API returned {resp.status_code}: {resp.text[:200]}")
            return None if not events else events
        data = resp.json()
        if not isinstance(data, list):
            print(f"Warning: unexpected events API response: {str(data)[:200]}")
            return None if not events else events
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
    resp = _get_with_retries(url)
    if resp is None:
        return {}
    if resp.status_code == 200:
        data = resp.json()
        if data:
            return data
    return {}


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

    sorted_langs = sorted(lang_counter.items(), key=lambda x: x[1], reverse=True)
    total = sum(lang_counter.values())
    display_langs = sorted_langs[:3]
    other_total = sum(byte_count for _, byte_count in sorted_langs[3:])
    if other_total > 0:
        display_langs.append(("Other", other_total))

    items = [(lang, byte_count) for lang, byte_count in display_langs]
    return _make_language_bar(items, total)


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

    updated_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    readme = f"""<table style="border-color: transparent;" cellspacing=0>
<tr>
<td valign="center" width="62%">

# Building with AI

**Artificial Intelligence**

I build around AI: tools, systems, and experiments that turn vague ideas into usable workflows.

**Tools & Systems**

I care about the moment when intelligence stops being only a chat box and starts becoming something that can plan, call tools, remember context, and help with real work.

**Open Questions**

How should humans collaborate with AI when the answer is not only text, but also an action, a process, or a small system?

</td>
<td valign="top" width="38%">
<p align="right">

***

> Human × AI, not Human vs. AI

***

<img width="420" src="https://github-readme-stats.vercel.app/api?username=jyh20030112&show_icons=true&hide_border=true&theme=transparent" />

***

> 把想法变成可运行的小系统

***

</p>
</td>
</tr>
</table>

<table style="border-color: transparent;" cellspacing=0>
<tr>
<td valign="top" width="64%">

[![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![AI](https://img.shields.io/badge/AI-111111?style=flat-square&logo=openai&logoColor=white)](https://github.com/jyh20030112)
[![GitHub](https://img.shields.io/badge/GitHub-jyh20030112-181717?style=flat-square&logo=github)](https://github.com/jyh20030112)

<!--START_SECTION:profile-stats-->
**Coding Rhythm**

> 数据由 GitHub Actions 自动更新 | Last Updated: {updated_at}

基于最近 **{total_pushes}** 次公开 Push 记录：

| Most Active Time | Most Productive Day | Main Language |
|:---:|:---:|:---:|
| {peak_period_cn.get(peak_period, peak_period)} | {peak_day} | {peak_lang} |

### Time Distribution

{period_chart}

### Weekday Distribution

{weekday_chart}

### Language Distribution

{lang_chart}
<!--END_SECTION:profile-stats-->

</td>
<td valign="top" width="36%">

**Currently**

> Building around AI

<table style="border-color: transparent;" cellspacing=0>
  <tr>
    <td valign="center">AI-native tools</td>
  </tr>
  <tr>
    <td valign="center">Agentic workflows</td>
  </tr>
  <tr>
    <td valign="center">Human-AI collaboration</td>
  </tr>
  <tr>
    <td valign="center">Small intelligent systems</td>
  </tr>
</table>

**Traces**

<table style="border-color: transparent;" cellspacing=0>
  <tr>
    <td valign="center">
      <a href="https://github.com/jyh20030112">
        <img src="https://img.shields.io/badge/AI--native-Tools-blue?style=flat-square" alt="AI-native Tools" />
      </a>
    </td>
  </tr>
  <tr>
    <td valign="center">
      <a href="https://github.com/jyh20030112">
        <img src="https://img.shields.io/badge/Intelligent-Workflows-green?style=flat-square" alt="Intelligent Workflows" />
      </a>
    </td>
  </tr>
  <tr>
    <td valign="center">
      <a href="https://github.com/jyh20030112">
        <img src="https://img.shields.io/badge/Human--AI-Collaboration-orange?style=flat-square" alt="Human-AI Collaboration" />
      </a>
    </td>
  </tr>
  <tr>
    <td valign="center">
      <a href="https://github.com/jyh20030112">
        <img src="https://img.shields.io/badge/Small-Systems-purple?style=flat-square" alt="Small Systems" />
      </a>
    </td>
  </tr>
</table>

</td>
</tr>
</table>

<table style="border-color: transparent;" cellspacing=0>
<tr>
<td valign="top" width="34%">

### Direction

AI as a material for building.

Not only prompts, not only models, but interfaces, tools, memory, workflows, and the quiet parts that make intelligence useful.

</td>
<td valign="top" width="33%">

### Experiments

Small systems first.

I like projects that can be touched, run, broken, repaired, and slowly shaped into something clearer.

</td>
<td valign="top" width="33%">

<img src="https://github-readme-stats.vercel.app/api/top-langs/?username=jyh20030112&layout=compact&hide_border=true&theme=transparent" />

</td>
</tr>
</table>

<details>
<summary>About the activity stats</summary>
<br>

These charts are generated from recent public Push events. Language distribution aggregates GitHub language bytes from repositories that appear in those Push events, then renders everything as Unicode text bars.

</details>

<p align="right">Building with AI, one small system at a time.</p>
"""
    return readme


def main():
    print("=" * 50)
    print("  GitHub Profile Stats Generator")
    print("=" * 50)

    print("\n[1/3] 获取 Push 事件...")
    events = fetch_events()
    if events is None:
        print("\nGitHub events API 暂时不可用，跳过 README 更新，避免写入空统计。")
        return
    if not events:
        print("\n未获取到 Push 事件，跳过 README 更新，避免写入空统计。")
        return

    period_counter = Counter()
    day_counter = Counter()
    lang_counter = Counter()
    repo_lang_cache = {}
    pushed_repos_seen = set()

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
        if repo_name and repo_name not in pushed_repos_seen:
            if repo_name not in repo_lang_cache:
                repo_lang_cache[repo_name] = fetch_repo_languages(repo_name)

            for lang, byte_count in repo_lang_cache[repo_name].items():
                lang_counter[lang] += byte_count
            pushed_repos_seen.add(repo_name)

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
