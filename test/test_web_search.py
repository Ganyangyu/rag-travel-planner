"""At least three distinct readable sources; shortages never count as successes."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import crawler


def article(index, city="上海"):
    return {"title": f"{city}攻略{index}", "text": f"{city}旅行正文{index}" * 30,
            "url": f"https://example.com/guide/{index}", "platform": "example.com", "kind": "travel_post"}


class WebSearchTests(unittest.TestCase):
    def test_initial_one_article_is_supplemented_to_three(self):
        one = article(1)
        hit = {**one, "query": "上海路线"}
        updates = []
        with patch.object(crawler, "search_xhs_browser", return_value=[]), \
             patch.object(crawler, "_search", return_value=[hit]), \
             patch.object(crawler, "crawl_note", return_value=one), \
             patch.object(crawler, "_directory_guides", return_value=[article(2), article(3)]) as directory:
            notes = crawler.collect_guides(["上海路线"], "上海", progress=lambda p,s:updates.append(p))
        self.assertEqual(len(notes), 3)
        directory.assert_called_once_with("上海")
        self.assertEqual(updates, sorted(updates))
        self.assertEqual((updates[0], updates[-1]), (0, 1))

    def test_tracking_variants_and_duplicate_bodies_do_not_count(self):
        first = article(1)
        duplicate_url = {**article(2), "url": first["url"] + "?tracking=2"}
        duplicate_body = {**article(3), "text": first["text"]}
        self.assertEqual(crawler._distinct_articles([first, duplicate_url, duplicate_body]), [first])

    def test_three_readable_articles_do_not_need_directory(self):
        notes = [article(i) for i in range(3)]
        with patch.object(crawler, "search_xhs_browser", return_value=notes), \
             patch.object(crawler, "_search", return_value=[]), \
             patch.object(crawler, "_directory_guides") as directory:
            result = crawler.collect_guides(["上海"], "上海")
        self.assertEqual(len(result), 3)
        directory.assert_not_called()

    def test_shortage_is_reported_without_inventing_sources(self):
        messages = []
        with patch.object(crawler, "search_xhs_browser", return_value=[]), \
             patch.object(crawler, "_search", return_value=[]), \
             patch.object(crawler, "_directory_guides", return_value=[article(1)]):
            result = crawler.collect_guides(["上海"], "上海", report=messages.append)
        self.assertEqual(len(result), 1)
        self.assertIn("未达到三篇", messages[-1])

    def test_title_only_is_preserved_but_does_not_count_toward_three(self):
        title = {**article(9), "text": "", "kind": "title_only"}
        with patch.object(crawler, "search_xhs_browser", return_value=[title]), \
             patch.object(crawler, "_search", return_value=[]), \
             patch.object(crawler, "_directory_guides", return_value=[article(1), article(2), article(3)]):
            result = crawler.collect_guides(["上海"], "上海")
        self.assertEqual(len(result), 4)
        self.assertEqual(result[-1]["kind"], "title_only")
        self.assertEqual(len(crawler._distinct_articles(result)), 3)


if __name__ == "__main__":
    unittest.main()
