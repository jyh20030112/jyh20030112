import concurrent.futures
import json
import math
import os
import pathlib
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

GITHUB_USERNAME = "jyh20030112"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_API_URL = "https://api.github.com"
API_VERSION = "2022-11-28"
README_PATH = pathlib.Path("README.md")
CACHE_PATH = pathlib.Path(".github/data/commit-stats.json")
CACHE_VERSION = 1
SEARCH_PAGE_SIZE = 100
MAX_SEARCH_RESULTS = 1_000
DETAIL_WORKERS = 2
START_MARKER = "<!--START_SECTION:profile-stats-->"
END_MARKER = "<!--END_SECTION:profile-stats-->"
SHANGHAI = ZoneInfo("Asia/Shanghai")

HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "GitHub-Profile-Stats",
    "X-GitHub-Api-Version": API_VERSION,
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

TIME_PERIODS = (
    ("night", 0, 8, "🌙 00–08"),
    ("morning", 8, 12, "🌞 08–12"),
    ("afternoon", 12, 18, "🌤️ 12–18"),
    ("evening", 18, 24, "🌆 18–24"),
)

WEEKDAY_LABELS = (
    "🐔 Monday",
    "🐱 Tuesday",
    "🐶 Wednesday",
    "🐮 Thursday",
    "🐯 Friday",
    "🐰 Saturday",
    "🐲 Sunday",
)

LANGUAGE_BY_SUFFIX = {
    ".astro": "Astro",
    ".c": "C",
    ".cc": "C++",
    ".cjs": "JavaScript",
    ".cpp": "C++",
    ".cs": "C#",
    ".css": "CSS",
    ".cxx": "C++",
    ".dart": "Dart",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".fs": "F#",
    ".fsx": "F#",
    ".go": "Go",
    ".h": "C",
    ".hpp": "C++",
    ".html": "HTML",
    ".htm": "HTML",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".less": "Less",
    ".lua": "Lua",
    ".m": "Objective-C",
    ".mm": "Objective-C++",
    ".mjs": "JavaScript",
    ".mts": "TypeScript",
    ".php": "PHP",
    ".pl": "Perl",
    ".py": "Python",
    ".pyi": "Python",
    ".r": "R",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".sass": "Sass",
    ".scala": "Scala",
    ".scss": "SCSS",
    ".sh": "Shell",
    ".sql": "SQL",
    ".svelte": "Svelte",
    ".swift": "Swift",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".cts": "TypeScript",
    ".vue": "Vue",
    ".zig": "Zig",
}

SPECIAL_FILENAMES = {
    "cmakelists.txt": "CMake",
    "dockerfile": "Dockerfile",
    "gemfile": "Ruby",
    "makefile": "Makefile",
    "rakefile": "Ruby",
}

IGNORED_FILENAMES = {
    "bun.lock",
    "bun.lockb",
    "cargo.lock",
    "composer.lock",
    "go.sum",
    "package-lock.json",
    "pipfile.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
}

IGNORED_PATH_PARTS = {
    ".cache",
    ".next",
    ".nuxt",
    ".output",
    ".venv",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "profile-3d-contrib",
    "target",
    "vendor",
}

ZERO_WIDTH_CHARS = {"\ufe0f", "\ufe0e"}


def _visual_width(value):
    width = 0
    for char in str(value):
        if char in ZERO_WIDTH_CHARS:
            continue
        width += 2 if ord(char) > 127 else 1
    return width


def _pad_visual(value, target_width):
    current = _visual_width(value)
    return str(value) + " " * max(target_width - current, 1)


def _make_count_bar(items, total, bar_width=25):
    label_width = max(_visual_width(label) for label, _ in items) + 2
    value_width = max(len(f"{value:,} commits") for _, value in items) + 1
    lines = []

    for label, value in items:
        percentage = value / total * 100 if total else 0.0
        filled = int(bar_width * value / total) if total else 0
        bar = "█" * filled + "░" * (bar_width - filled)
        count = f"{value:,} commits"
        lines.append(
            f"{_pad_visual(label, label_width)}"
            f"{_pad_visual(count, value_width)}"
            f"{bar}  {percentage:5.1f} %"
        )

    return "```text\n" + "\n".join(lines) + "\n```"


def _make_language_bar(items, total, bar_width=25):
    label_width = max(_visual_width(label) for label, _ in items) + 2
    value_width = max(len(f"{value:,} lines") for _, value in items) + 1
    lines = []

    for label, value in items:
        percentage = value / total * 100 if total else 0.0
        filled = int(bar_width * value / total) if total else 0
        bar = "█" * filled + "░" * (bar_width - filled)
        changes = f"{value:,} lines"
        lines.append(
            f"{_pad_visual(label, label_width)}"
            f"{_pad_visual(changes, value_width)}"
            f"{bar}  {percentage:5.1f} %"
        )

    return "```text\n" + "\n".join(lines) + "\n```"


def _request_json(client, url, params=None, retries=6, allow_not_found=False):
    for attempt in range(1, retries + 1):
        try:
            response = client.get(url, params=params)
        except httpx.HTTPError as error:
            if attempt == retries:
                raise RuntimeError(f"Request failed for {url}: {error}") from error
            time.sleep(attempt * 2)
            continue

        if response.status_code == 404 and allow_not_found:
            return None
        if response.status_code == 200:
            return response.json()

        if response.status_code in {403, 429}:
            remaining = response.headers.get("X-RateLimit-Remaining")
            if remaining == "0":
                reset = response.headers.get("X-RateLimit-Reset", "unknown")
                raise RuntimeError(f"GitHub API rate limit exhausted; reset at {reset}")
            if attempt < retries:
                retry_after = response.headers.get("Retry-After")
                delay = (
                    int(retry_after)
                    if retry_after and retry_after.isdigit()
                    else attempt * 10
                )
                print(
                    f"GitHub asked us to slow down; retrying in {min(delay, 30)} seconds..."
                )
                time.sleep(min(delay, 30))
                continue

        if response.status_code >= 500 and attempt < retries:
            time.sleep(attempt * 2)
            continue

        body = response.text[:300].replace("\n", " ")
        raise RuntimeError(
            f"GitHub API returned {response.status_code} for {url}: {body}"
        )

    raise RuntimeError(f"Request failed for {url}")


def _search_query(start_date, end_date):
    return (
        f"author:{GITHUB_USERNAME} "
        f"author-date:{start_date.isoformat()}..{end_date.isoformat()}"
    )


def _search_commit_range(client, start_date, end_date):
    probe = _request_json(
        client,
        f"{GITHUB_API_URL}/search/commits",
        params={"q": _search_query(start_date, end_date), "per_page": 1},
    )
    if probe.get("incomplete_results"):
        raise RuntimeError("GitHub returned incomplete commit search results")

    total = int(probe.get("total_count", 0))
    if total > MAX_SEARCH_RESULTS and start_date < end_date:
        midpoint = start_date + (end_date - start_date) // 2
        left = _search_commit_range(client, start_date, midpoint)
        right = _search_commit_range(client, midpoint + timedelta(days=1), end_date)
        return left + right

    if total > MAX_SEARCH_RESULTS:
        raise RuntimeError(
            f"More than {MAX_SEARCH_RESULTS:,} commits were authored on {start_date}; "
            "the search range cannot be divided further"
        )

    commits = []
    pages = math.ceil(total / SEARCH_PAGE_SIZE)
    for page in range(1, pages + 1):
        page_data = _request_json(
            client,
            f"{GITHUB_API_URL}/search/commits",
            params={
                "q": _search_query(start_date, end_date),
                "sort": "author-date",
                "order": "desc",
                "per_page": SEARCH_PAGE_SIZE,
                "page": page,
            },
        )
        if page_data.get("incomplete_results"):
            raise RuntimeError("GitHub returned incomplete commit search results")
        commits.extend(page_data.get("items", []))
        if page < pages:
            time.sleep(2)

    return commits


def fetch_all_public_commits(client):
    commits = _search_commit_range(client, date(1970, 1, 1), datetime.now(UTC).date())
    unique_commits = {}

    for item in commits:
        sha = item.get("sha")
        authored_at = item.get("commit", {}).get("author", {}).get("date")
        detail_url = item.get("url")
        if sha and authored_at and detail_url:
            unique_commits.setdefault(
                sha,
                {"sha": sha, "authored_at": authored_at, "detail_url": detail_url},
            )

    return sorted(unique_commits.values(), key=lambda item: item["authored_at"])


def classify_time_period(hour):
    for name, start, end, _label in TIME_PERIODS:
        if start <= hour < end:
            return name
    raise ValueError(f"Hour outside expected range: {hour}")


def classify_language(filename):
    path = pathlib.PurePosixPath(filename)
    lower_parts = {part.lower() for part in path.parts}
    basename = path.name.lower()

    if lower_parts & IGNORED_PATH_PARTS:
        return None
    if basename in IGNORED_FILENAMES:
        return None
    if ".min." in basename or basename.endswith(".map"):
        return None
    if basename in SPECIAL_FILENAMES:
        return SPECIAL_FILENAMES[basename]

    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower())


def _fetch_commit_languages(client, detail_url):
    languages = Counter()
    page = 1

    while True:
        data = _request_json(
            client,
            detail_url,
            params={"per_page": 100, "page": page},
            allow_not_found=True,
        )
        if data is None:
            return {}

        files = data.get("files", [])
        for changed_file in files:
            language = classify_language(changed_file.get("filename", ""))
            changes = int(changed_file.get("changes", 0) or 0)
            if language and changes > 0:
                languages[language] += changes

        if len(files) < 100:
            break
        page += 1

    return dict(languages)


def _load_cache():
    if not CACHE_PATH.exists():
        return {}

    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if data.get("version") != CACHE_VERSION or data.get("username") != GITHUB_USERNAME:
        return {}
    return data.get("commits", {})


def _write_cache(commit_languages):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": CACHE_VERSION,
        "username": GITHUB_USERNAME,
        "commits": dict(sorted(commit_languages.items())),
    }
    CACHE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fetch_contributed_languages(client, commits):
    cached = _load_cache()
    current_shas = {commit["sha"] for commit in commits}
    languages_by_commit = {
        sha: languages for sha, languages in cached.items() if sha in current_shas
    }
    missing = [commit for commit in commits if commit["sha"] not in languages_by_commit]

    if missing:
        print(f"Fetching changed files for {len(missing):,} uncached commits...")
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=DETAIL_WORKERS
        ) as executor:
            futures = {
                executor.submit(
                    _fetch_commit_languages, client, commit["detail_url"]
                ): commit
                for commit in missing
            }
            for index, future in enumerate(
                concurrent.futures.as_completed(futures), start=1
            ):
                commit = futures[future]
                languages_by_commit[commit["sha"]] = future.result()
                if index % 25 == 0 or index == len(missing):
                    _write_cache(languages_by_commit)
                    print(f"  Processed {index:,}/{len(missing):,} commit details")

    return languages_by_commit


def build_counters(commits, languages_by_commit):
    period_counter = Counter()
    weekday_counter = Counter()
    language_counter = Counter()

    for commit in commits:
        authored_at = datetime.fromisoformat(commit["authored_at"])
        local_time = authored_at.astimezone(SHANGHAI)
        period_counter[classify_time_period(local_time.hour)] += 1
        weekday_counter[local_time.weekday()] += 1
        language_counter.update(languages_by_commit.get(commit["sha"], {}))

    return period_counter, weekday_counter, language_counter


def create_time_distribution_chart(period_counter):
    total = sum(period_counter.values())
    items = [
        (label, period_counter.get(name, 0))
        for name, _start, _end, label in TIME_PERIODS
    ]
    return _make_count_bar(items, total)


def create_weekday_chart(weekday_counter):
    total = sum(weekday_counter.values())
    items = [
        (label, weekday_counter.get(index, 0))
        for index, label in enumerate(WEEKDAY_LABELS)
    ]
    return _make_count_bar(items, total)


def create_language_chart(language_counter):
    if not language_counter:
        return "No code-language changes found."

    sorted_languages = language_counter.most_common()
    total = sum(language_counter.values())
    display_languages = sorted_languages[:3]
    other_total = sum(value for _language, value in sorted_languages[3:])
    if other_total:
        display_languages.append(("Other", other_total))

    return _make_language_bar(display_languages, total)


def render_stats_section(commits, period_counter, weekday_counter, language_counter):
    total_commits = len(commits)
    period_labels = {name: label for name, _start, _end, label in TIME_PERIODS}
    peak_period_count = max(period_counter.values())
    peak_period = " / ".join(
        period_labels[name]
        for name, _start, _end, _label in TIME_PERIODS
        if period_counter.get(name, 0) == peak_period_count
    )
    peak_weekday_count = max(weekday_counter.values())
    peak_weekday = " / ".join(
        label.split(" ", 1)[1]
        for index, label in enumerate(WEEKDAY_LABELS)
        if weekday_counter.get(index, 0) == peak_weekday_count
    )
    primary_language = (
        language_counter.most_common(1)[0][0] if language_counter else "N/A"
    )

    return f"""Based on **{total_commits:,}** public commits authored by [@{GITHUB_USERNAME}](https://github.com/{GITHUB_USERNAME}):

| Most Active Time | Most Productive Day | Primary Language |
|:---:|:---:|:---:|
| {peak_period} | {peak_weekday} | {primary_language} |

### Time Distribution

{create_time_distribution_chart(period_counter)}

### Weekday Distribution

{create_weekday_chart(weekday_counter)}

### Language Distribution

{create_language_chart(language_counter)}"""


def replace_stats_section(readme, stats_section):
    start = readme.find(START_MARKER)
    end = readme.find(END_MARKER)
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError("README statistics markers are missing or out of order")

    content_start = start + len(START_MARKER)
    return readme[:content_start] + "\n" + stats_section.strip() + "\n" + readme[end:]


def main():
    print("GitHub profile commit statistics")
    print("Searching all public commits authored by the profile owner...")

    with httpx.Client(headers=HEADERS, timeout=60.0, follow_redirects=True) as client:
        commits = fetch_all_public_commits(client)
        if not commits:
            print("No public commits found; README was left unchanged.")
            return

        print(f"Found {len(commits):,} unique public commits")
        languages_by_commit = fetch_contributed_languages(client, commits)

    period_counter, weekday_counter, language_counter = build_counters(
        commits, languages_by_commit
    )
    stats_section = render_stats_section(
        commits, period_counter, weekday_counter, language_counter
    )
    current_readme = README_PATH.read_text(encoding="utf-8")
    updated_readme = replace_stats_section(current_readme, stats_section)

    _write_cache(languages_by_commit)
    README_PATH.write_text(updated_readme, encoding="utf-8")
    print("README and commit-language cache updated successfully")


if __name__ == "__main__":
    main()
