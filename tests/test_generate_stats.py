import unittest
from collections import Counter

import generate_stats


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
