import unittest
from collections import Counter
from datetime import date
from unittest.mock import Mock, patch

import httpx

import generate_stats


class GitHubAPITests(unittest.TestCase):
    def setUp(self):
        self.sleep = self.enterContext(patch.object(generate_stats.time, "sleep"))
        self.enterContext(patch.object(generate_stats.time, "time", return_value=100.0))

    def mock_client(self, responses, authenticated=True):
        handler = Mock(side_effect=responses)
        headers = {"Authorization": "Bearer test-token"} if authenticated else {}
        client = self.enterContext(
            httpx.Client(transport=httpx.MockTransport(handler), headers=headers)
        )
        return client, handler

    def test_waits_for_exhausted_search_quota_to_reset(self):
        client, handler = self.mock_client([
            httpx.Response(403, headers={
                "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "130"
            }, json={"message": "API rate limit exceeded"}),
            httpx.Response(200, json={"ok": True}),
        ])

        data = generate_stats._request_json(client, "https://api.github.com/search/commits")

        self.assertEqual(data, {"ok": True})
        self.assertEqual(handler.call_count, 2)
        self.sleep.assert_any_call(31.0)

    def test_honors_retry_after_without_shortening_it(self):
        client, handler = self.mock_client([
            httpx.Response(429, headers={"Retry-After": "120"}),
            httpx.Response(200, json={"ok": True}),
        ])

        generate_stats._request_json(client, "https://api.github.com/search/commits")

        self.assertEqual(handler.call_count, 2)
        self.sleep.assert_any_call(120)

    def test_uses_longer_wait_when_both_rate_limit_headers_are_present(self):
        client, _ = self.mock_client([
            httpx.Response(429, headers={
                "Retry-After": "10", "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": "130",
            }),
            httpx.Response(200, json={}),
        ])

        generate_stats._request_json(client, "https://api.github.com/search/commits")

        self.sleep.assert_any_call(31.0)

    def test_secondary_limit_without_headers_waits_at_least_a_minute(self):
        client, _ = self.mock_client([
            httpx.Response(403, json={"message": "You have exceeded a secondary rate limit"}),
            httpx.Response(200, json={}),
        ])

        generate_stats._request_json(client, "https://api.github.com/search/commits")

        self.sleep.assert_any_call(60)

    def test_does_not_retry_a_permission_error(self):
        client, handler = self.mock_client([
            httpx.Response(403, json={"message": "Resource not accessible by integration"})
        ])

        with self.assertRaisesRegex(RuntimeError, "returned 403"):
            generate_stats._request_json(client, "https://api.github.com/repos/owner/repo")

        self.assertEqual(handler.call_count, 1)
        self.sleep.assert_not_called()

    def test_rate_limit_retries_are_bounded(self):
        client, handler = self.mock_client([
            httpx.Response(429, headers={"Retry-After": "1"}),
            httpx.Response(429, headers={"Retry-After": "1"}),
        ])

        with self.assertRaisesRegex(RuntimeError, "returned 429"):
            generate_stats._request_json(
                client, "https://api.github.com/search/commits", retries=2
            )

        self.assertEqual(handler.call_count, 2)

    def test_long_rate_limit_does_not_exceed_the_ci_wait_budget(self):
        client, handler = self.mock_client([
            httpx.Response(429, headers={"Retry-After": "3600"})
        ])

        with self.assertRaisesRegex(RuntimeError, "exceeds.*retry budget"):
            generate_stats._request_json(client, "https://api.github.com/search/commits")

        self.assertEqual(handler.call_count, 1)
        self.assertNotIn(3600, [call.args[0] for call in self.sleep.call_args_list])

    def test_unauthenticated_search_uses_the_lower_request_budget(self):
        client, _ = self.mock_client([httpx.Response(200, json={})], authenticated=False)

        generate_stats._request_json(client, "https://api.github.com/search/commits")

        self.sleep.assert_called_once_with(6.1)

    def test_incomplete_search_is_retried_without_returning_partial_data(self):
        client, handler = self.mock_client([
            httpx.Response(200, json={
                "incomplete_results": True, "items": [{"sha": "partial"}],
            }),
            httpx.Response(200, json={
                "incomplete_results": False, "total_count": 1,
                "items": [{"sha": "complete"}],
            }),
        ])

        commits = generate_stats._search_commit_range(
            client, date(2026, 10, 1), date(2026, 10, 26)
        )

        self.assertEqual(commits, [{"sha": "complete"}])
        self.assertEqual(handler.call_count, 2)
        self.sleep.assert_any_call(5)

    def test_persistently_incomplete_search_still_fails(self):
        client, handler = self.mock_client([
            httpx.Response(200, json={"incomplete_results": True}) for _ in range(3)
        ])

        with self.assertRaisesRegex(RuntimeError, "incomplete.*after retries"):
            generate_stats._search_commit_range(
                client, date(2026, 10, 1), date(2026, 10, 26)
            )

        self.assertEqual(handler.call_count, 3)

    def test_reuses_the_first_search_page_and_paces_every_page(self):
        items = [{"sha": str(index)} for index in range(101)]
        client, handler = self.mock_client([
            httpx.Response(200, json={"total_count": 101, "items": items[:100]}),
            httpx.Response(200, json={"total_count": 101, "items": items[100:]}),
        ])

        commits = generate_stats._search_commit_range(
            client, date(2026, 10, 1), date(2026, 10, 26)
        )

        self.assertEqual(commits, items)
        self.assertEqual(handler.call_count, 2)
        self.assertEqual(
            [call.args[0].url.params["page"] for call in handler.call_args_list],
            ["1", "2"],
        )
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [2.1, 2.1])

    def test_large_search_splits_from_the_actual_oldest_commit(self):
        items = [
            {"sha": "a", "commit": {"author": {"date": "2026-01-01T00:00:00Z"}}},
            {"sha": "b", "commit": {"author": {"date": "2026-01-16T00:00:00Z"}}},
            {"sha": "c", "commit": {"author": {"date": "2026-01-20T00:00:00Z"}}},
        ]
        client, handler = self.mock_client([
            httpx.Response(200, json={"total_count": 3, "items": items[:2]}),
            httpx.Response(200, json={"total_count": 2, "items": items[:2]}),
            httpx.Response(200, json={"total_count": 1, "items": items[2:]}),
        ])

        with patch.multiple(generate_stats, MAX_SEARCH_RESULTS=2, SEARCH_PAGE_SIZE=2):
            commits = generate_stats._search_commit_range(client, None, date(2026, 1, 31))

        self.assertEqual(commits, items)
        self.assertEqual(
            [call.args[0].url.params["q"] for call in handler.call_args_list],
            [
                "author:jyh20030112 author-date:<=2026-01-31",
                "author:jyh20030112 author-date:2026-01-01..2026-01-16",
                "author:jyh20030112 author-date:2026-01-17..2026-01-31",
            ],
        )

    def test_single_day_search_overflow_is_not_silently_truncated(self):
        client, _ = self.mock_client([
            httpx.Response(200, json={"total_count": 3, "items": []})
        ])

        with patch.object(generate_stats, "MAX_SEARCH_RESULTS", 2):
            with self.assertRaisesRegex(RuntimeError, "cannot be divided further"):
                generate_stats._search_commit_range(
                    client, date(2026, 10, 26), date(2026, 10, 26)
                )

    def test_empty_search_returns_without_extra_requests(self):
        client, handler = self.mock_client([
            httpx.Response(200, json={"total_count": 0, "items": []})
        ])

        self.assertEqual(
            generate_stats._search_commit_range(client, None, date(2026, 10, 26)), []
        )
        self.assertEqual(handler.call_count, 1)


class TimePeriodTests(unittest.TestCase):
    def test_time_period_boundaries_are_exclusive(self):
        expected = {
            0: "night",
            7: "night",
            8: "morning",
            11: "morning",
            12: "afternoon",
            17: "afternoon",
            18: "evening",
            23: "evening",
        }

        for hour, period in expected.items():
            with self.subTest(hour=hour):
                self.assertEqual(generate_stats.classify_time_period(hour), period)


class LanguageClassificationTests(unittest.TestCase):
    def test_groups_related_extensions(self):
        self.assertEqual(generate_stats.classify_language("src/app.tsx"), "TypeScript")
        self.assertEqual(
            generate_stats.classify_language("src/worker.mjs"), "JavaScript"
        )
        self.assertEqual(generate_stats.classify_language("server/main.py"), "Python")

    def test_recognizes_extensionless_code_files(self):
        self.assertEqual(generate_stats.classify_language("Dockerfile"), "Dockerfile")
        self.assertEqual(generate_stats.classify_language("tools/Makefile"), "Makefile")

    def test_ignores_generated_dependencies_locks_and_docs(self):
        ignored = (
            "package-lock.json",
            "src/app.min.js",
            "dist/app.js",
            "node_modules/pkg/index.ts",
            "README.md",
            "profile-3d-contrib/profile.svg",
        )

        for filename in ignored:
            with self.subTest(filename=filename):
                self.assertIsNone(generate_stats.classify_language(filename))


class AggregationTests(unittest.TestCase):
    def test_counts_commits_and_changed_lines(self):
        commits = [
            {
                "sha": "a",
                "authored_at": "2026-08-24T08:30:00+08:00",
                "detail_url": "https://example.test/a",
            },
            {
                "sha": "b",
                "authored_at": "2026-08-24T19:30:00+08:00",
                "detail_url": "https://example.test/b",
            },
        ]
        languages = {
            "a": {"Python": 10},
            "b": {"Python": 5, "TypeScript": 20},
        }

        periods, weekdays, language_counts = generate_stats.build_counters(
            commits, languages
        )

        self.assertEqual(periods, Counter({"morning": 1, "evening": 1}))
        self.assertEqual(sum(weekdays.values()), 2)
        self.assertEqual(language_counts, Counter({"TypeScript": 20, "Python": 15}))


class ReadmeUpdateTests(unittest.TestCase):
    def test_replaces_only_the_marked_section(self):
        original = "before\n<!--START_SECTION:profile-stats-->\nold\n<!--END_SECTION:profile-stats-->\nafter\n"
        updated = generate_stats.replace_stats_section(original, "new")

        self.assertEqual(
            updated,
            "before\n<!--START_SECTION:profile-stats-->\nnew\n<!--END_SECTION:profile-stats-->\nafter\n",
        )

    def test_rendered_section_uses_commit_language(self):
        commits = [{"sha": "a"}]
        section = generate_stats.render_stats_section(
            commits,
            Counter({"morning": 1}),
            Counter({0: 1}),
            Counter({"Python": 12}),
        )

        self.assertIn("public commits authored by", section)
        self.assertIn("Primary Language", section)
        self.assertIn("12 lines", section)
        self.assertIn('<table width="100%"', section)
        self.assertIn("<strong>Time Distribution</strong>", section)
        self.assertNotIn("### Time Distribution", section)
        self.assertNotIn("Coding Rhythm", section)
        self.assertNotIn("Last Updated", section)
        self.assertNotIn("Push", section)

    def test_rendered_section_preserves_tied_peak_days(self):
        commits = [{"sha": "a"}, {"sha": "b"}]
        section = generate_stats.render_stats_section(
            commits,
            Counter({"morning": 2}),
            Counter({1: 1, 2: 1}),
            Counter({"Python": 12}),
        )

        self.assertIn("Tuesday / Wednesday", section)


if __name__ == "__main__":
    unittest.main()
