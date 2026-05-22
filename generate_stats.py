import os
import json
import platform
import requests
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

GITHUB_USERNAME = "jyh20030112"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
ASSETS_DIR = "assets"

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
WEEKDAY_NAMES_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

PERIOD_COLORS = {
    "morning": "#FFB74D",
    "afternoon": "#FF8A65",
    "evening": "#9575CD",
    "night": "#4FC3F7",
}

DAY_COLORS = [
    "#FF6B6B", "#FFD93D", "#6BCB77", "#4D96FF",
    "#9B59B6", "#FF8C42", "#36C9C6",
]

LANG_COLORS = [
    "#3572A5", "#DA5B0B", "#E34C26", "#563D7C", "#2B7489",
    "#F7DF1E", "#41B883", "#DE3423", "#F18E33", "#178600",
    "#555555", "#438EFF", "#FF6F00", "#FFD43B", "#3776AB",
]


def setup_cjk_font():
    system = platform.system()
    if system == "Darwin":
        candidates = ["PingFang SC", "Heiti SC", "STHeiti", "Apple SD Gothic Neo"]
    elif system == "Linux":
        candidates = [
            "WenQuanYi Micro Hei", "WenQuanYi Zen Hei",
            "Noto Sans CJK SC", "Noto Sans SC",
            "Droid Sans Fallback", "DejaVu Sans",
        ]
    else:
        candidates = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]

    for font_name in candidates:
        for f in fm.fontManager.ttflist:
            if font_name.lower() in f.name.lower():
                plt.rcParams["font.family"] = f.name
                print(f"Using font: {f.name}")
                return

    plt.rcParams["font.family"] = "sans-serif"
    print("Warning: No CJK font found, Chinese characters may not render")


setup_cjk_font()


def fetch_events():
    events = []
    for page in range(1, 6):
        url = f"https://api.github.com/users/{GITHUB_USERNAME}/events?per_page=100&page={page}"
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            break
        data = resp.json()
        if not data:
            break
        push_events = [e for e in data if e["type"] == "PushEvent"]
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
    resp = requests.get(url, headers=HEADERS, timeout=30)
    if resp.status_code == 200:
        data = resp.json()
        if data:
            total = sum(data.values())
            primary_lang = max(data, key=data.get)
            return primary_lang, data
    return "Unknown", {}


def create_time_distribution_chart(period_counter):
    fig, ax = plt.subplots(figsize=(7, 4.5), facecolor="#0D1117")
    ax.set_facecolor("#0D1117")

    order = ["morning", "afternoon", "evening", "night"]
    labels_cn = ["上午 6-12", "下午 12-18", "傍晚 18-24", "深夜 0-6"]
    values = [period_counter.get(p, 0) for p in order]
    colors = [PERIOD_COLORS[p] for p in order]

    bars = ax.bar(range(len(order)), values, color=colors, edgecolor="#30363D", linewidth=0.5, width=0.6)

    all_zero = max(values) == 0
    max_val = max(values) if not all_zero else 1
    if not all_zero:
        for bar, val in zip(bars, values):
            if val > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max_val * 0.02,
                    str(val),
                    ha="center",
                    va="bottom",
                    color="#C9D1D9",
                    fontsize=10,
                    fontweight="bold",
                )

    ax.set_xticks(range(len(order)))
    ax.set_xticklabels(labels_cn, color="#C9D1D9", fontsize=11)
    ax.set_ylabel("Push 次数", color="#8B949E", fontsize=11)
    ax.set_title("� Push 时间段分布", color="#58A6FF", fontsize=16, fontweight="bold", pad=12)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#30363D")
    ax.spines["bottom"].set_color("#30363D")
    ax.tick_params(colors="#8B949E")
    ax.yaxis.grid(True, color="#30363D", linewidth=0.5, alpha=0.5)
    ax.set_axisbelow(True)
    ax.set_ylim(0, max(max_val * 1.2, 1.5))

    fig.tight_layout()
    fig.savefig(f"{ASSETS_DIR}/time_distribution.png", dpi=150, facecolor="#0D1117", edgecolor="none")
    plt.close(fig)
    print(f"Time distribution saved: {dict(period_counter)}")


def create_weekday_chart(day_counter):
    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor="#0D1117")
    ax.set_facecolor("#0D1117")

    days = list(range(7))
    values = [day_counter.get(d, 0) for d in days]
    colors = DAY_COLORS

    bars = ax.bar(days, values, color=colors, edgecolor="#30363D", linewidth=0.5, width=0.65)

    all_zero = max(values) == 0
    max_val = max(values) if not all_zero else 1
    if not all_zero:
        for bar, val in zip(bars, values):
            if val > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max_val * 0.02,
                    str(val),
                    ha="center",
                    va="bottom",
                    color="#C9D1D9",
                    fontsize=10,
                    fontweight="bold",
                )

    ax.set_xticks(days)
    ax.set_xticklabels(WEEKDAY_NAMES_CN, color="#C9D1D9", fontsize=11)
    ax.set_ylabel("Push 次数", color="#8B949E", fontsize=11)
    ax.set_title("📆 星期几最活跃？", color="#58A6FF", fontsize=16, fontweight="bold", pad=12)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#30363D")
    ax.spines["bottom"].set_color("#30363D")
    ax.tick_params(colors="#8B949E")
    ax.yaxis.grid(True, color="#30363D", linewidth=0.5, alpha=0.5)
    ax.set_axisbelow(True)
    ax.set_ylim(0, max(max_val * 1.2, 1.5))

    fig.tight_layout()
    fig.savefig(f"{ASSETS_DIR}/weekday_distribution.png", dpi=150, facecolor="#0D1117", edgecolor="none")
    plt.close(fig)
    print(f"Weekday distribution saved: {dict(day_counter)}")


def create_language_chart(lang_counter):
    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor="#0D1117")
    ax.set_facecolor("#0D1117")

    if not lang_counter:
        ax.text(0.5, 0.5, "暂无数据", ha="center", va="center", color="#8B949E", fontsize=14, transform=ax.transAxes)
        ax.set_title("💻 编程语言分布", color="#58A6FF", fontsize=16, fontweight="bold", pad=12)
        fig.tight_layout()
        fig.savefig(f"{ASSETS_DIR}/language_distribution.png", dpi=150, facecolor="#0D1117", edgecolor="none")
        plt.close(fig)
        return

    sorted_langs = sorted(lang_counter.items(), key=lambda x: x[1], reverse=True)
    top_langs = sorted_langs[:10]

    labels = [lang for lang, _ in top_langs]
    values = [count for _, count in top_langs]
    colors = LANG_COLORS[: len(labels)]

    x_pos = range(len(labels))
    bars = ax.bar(x_pos, values, color=colors, edgecolor="#30363D", linewidth=0.5, width=0.6)

    max_val = max(values) if values else 1
    for bar, val in zip(bars, values):
        if val > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max_val * 0.02,
                str(val),
                ha="center",
                va="bottom",
                color="#C9D1D9",
                fontsize=10,
                fontweight="bold",
            )

    ax.set_xticks(list(x_pos))
    ax.set_xticklabels(labels, color="#C9D1D9", fontsize=11, rotation=30, ha="right")
    ax.set_ylabel("Push 次数", color="#8B949E", fontsize=11)
    ax.set_title("💻 编程语言分布", color="#58A6FF", fontsize=16, fontweight="bold", pad=12)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#30363D")
    ax.spines["bottom"].set_color("#30363D")
    ax.tick_params(colors="#8B949E")
    ax.yaxis.grid(True, color="#30363D", linewidth=0.5, alpha=0.5)
    ax.set_axisbelow(True)
    ax.set_ylim(0, max(max_val * 1.2, 1.5))

    fig.tight_layout()
    fig.savefig(f"{ASSETS_DIR}/language_distribution.png", dpi=150, facecolor="#0D1117", edgecolor="none")
    plt.close(fig)
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
    os.makedirs(ASSETS_DIR, exist_ok=True)

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
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    print("  README.md 已更新!")

    print("\n" + "=" * 50)
    print("  完成! 所有图表已生成。")
    print("=" * 50)


if __name__ == "__main__":
    main()
