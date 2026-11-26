"""Local page samples test search states, extraction and missing detail bodies."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import crawler


URL = "https://www.xiaohongshu.com/search_result?keyword=test"
SIGNED = "https://www.xiaohongshu.com/explore/0123456789abcdef01234567?xsec_token=fixture"
CARD = f'<section class="note-item"><a class="cover" href="{SIGNED}"></a><a class="title">上海五日游慢游攻略</a></section>'


class XhsTests(unittest.TestCase):
    def test_shared_session_bootstraps_new_browser(self):
        playwright = MagicMock()
        context = playwright.chromium.launch_persistent_context.return_value
        context.cookies.return_value = []
        with patch.object(crawler, "XHS_COOKIE", "web_session=test-session; a1=test-browser-id"), patch.dict(os.environ, {}, clear=True):
            self.assertIs(crawler._browser_context(playwright), context)
        cookies = context.add_cookies.call_args.args[0]
        self.assertEqual({c["name"] for c in cookies}, {"web_session", "a1"})
        self.assertTrue(all(c["domain"] == ".xiaohongshu.com" for c in cookies))

    def test_shared_session_does_not_overwrite_personal_login(self):
        playwright = MagicMock()
        context = playwright.chromium.launch_persistent_context.return_value
        context.cookies.return_value = [{"name": "web_session", "value": "personal-session"}]
        with patch.object(crawler, "XHS_COOKIE", "web_session=shared-session"), patch.dict(os.environ, {}, clear=True):
            crawler._browser_context(playwright)
        context.add_cookies.assert_not_called()

    def test_explicit_cookie_environment_overrides_personal_login(self):
        playwright = MagicMock()
        context = playwright.chromium.launch_persistent_context.return_value
        context.cookies.return_value = [{"name": "web_session", "value": "previous-session"}]
        with patch.object(crawler, "XHS_COOKIE", "web_session=new-session"), patch.dict(os.environ, {"XHS_COOKIE": "web_session=new-session"}):
            crawler._browser_context(playwright)
        self.assertEqual(context.add_cookies.call_args.args[0][0]["value"], "new-session")

    def test_normal_card_preserves_title_and_signed_url(self):
        snap = crawler._xhs_snapshot(URL, CARD)
        self.assertEqual((snap["state"], snap["card_matches"], snap["parsed"]), ("cards", 1, 1))
        self.assertEqual(snap["cards"][0], {"title": "上海五日游慢游攻略", "url": SIGNED})

    def test_explicit_empty_is_not_login(self):
        snap = crawler._xhs_snapshot(URL, '<main>没有找到相关笔记，试试其他关键词</main>')
        self.assertEqual(snap["state"], "empty")

    def test_redirect_during_render_is_retried(self):
        page = MagicMock()
        page.url = URL
        page.content.side_effect = [RuntimeError("page is navigating"), CARD]
        self.assertEqual(crawler._wait_xhs(page)["state"], "cards")
        page.wait_for_timeout.assert_called_once()

    def test_loading_and_card_selector_failure_are_different(self):
        self.assertEqual(crawler._xhs_snapshot(URL, '<main>加载中</main>')["state"], "loading")
        snap = crawler._xhs_snapshot(URL, '<section class="note-item"><span>可见笔记但没有链接</span></section>')
        self.assertEqual((snap["state"], snap["card_matches"], snap["parsed"]), ("card_parse_failed", 1, 0))

    def test_waits_for_delayed_cards_and_records_render_timeout(self):
        page = MagicMock()
        page.url = URL
        page.content.side_effect = ['<main>加载中</main>', CARD]
        self.assertEqual(crawler._wait_xhs(page)["state"], "cards")
        page.wait_for_timeout.assert_called_once()
        page.content.side_effect = None
        page.content.return_value = '<main>仍在加载</main>'
        self.assertEqual(crawler._wait_xhs(page, timeout=0)["state"], "render_timeout")

    def test_transient_login_shell_is_not_final_login_diagnosis(self):
        page = MagicMock()
        page.url = URL
        page.content.side_effect = ['<div class="login-container">扫码登录</div>', '<main>当前网络存在风险</main>']
        self.assertEqual(crawler._wait_xhs(page)["state"], "restricted")
        page.wait_for_timeout.assert_called_once()

    def test_login_verification_and_restriction_are_distinct(self):
        for html, state in [('<div class="login-container">扫码登录</div>', "login_required"),
                            ('<main>请完成验证</main>', "verification"),
                            ('<main>访问受限</main>', "restricted")]:
            with self.subTest(state=state):
                self.assertEqual(crawler._xhs_snapshot(URL, html)["state"], state)
        snap = crawler._xhs_snapshot("https://www.xiaohongshu.com/website-login/error?error_code=300012&xsec_token=secret", "")
        self.assertEqual(snap["state"], "restricted")
        self.assertEqual(snap["code"], "300012")
        self.assertNotIn("secret", snap["path"])

    def test_missing_detail_keeps_real_card_as_title_only(self):
        page = MagicMock()
        page.url = SIGNED
        page.content.return_value = '<main>加载详情</main>'
        page.locator.return_value.wait_for.side_effect = TimeoutError()
        page.locator.return_value.count.return_value = 0
        note = crawler._read_xhs_detail(page, {"title": "上海五日游慢游攻略", "url": SIGNED}, "上海五日游")
        self.assertEqual((note["kind"], note["text"], note["detail_state"]), ("title_only", "", "body_missing"))
        self.assertEqual(note["title"], "上海五日游慢游攻略")
        self.assertEqual(note["url"], SIGNED)
        self.assertEqual(crawler.format_notes([note]), "")

    def test_normal_detail_reads_only_current_note_body(self):
        page = MagicMock()
        page.url = SIGNED
        page.content.return_value = '<main>正文</main>'
        body, title = MagicMock(), MagicMock()
        body.count.return_value = title.count.return_value = 1
        body.first.is_visible.return_value = title.first.is_visible.return_value = True
        body.first.inner_text.return_value = '外滩与豫园慢游，中午在同片区休息。'
        title.first.inner_text.return_value = '上海外滩豫园路线'
        page.locator.side_effect = lambda selector: body if selector == '#detail-desc' else title
        note = crawler._read_xhs_detail(page, {"title": "卡片标题", "url": SIGNED}, "上海 外滩 豫园")
        self.assertEqual(note["kind"], "article")
        self.assertEqual(note["detail_state"], "body_read")
        self.assertEqual(note["title"], "上海外滩豫园路线")
        self.assertIn('中午', note["text"])

    def test_initial_state_detail_matches_requested_note_id(self):
        page = MagicMock()
        page.url = SIGNED
        page.content.return_value = '<main>详情加载中</main>'
        page.locator.return_value.count.return_value = 0
        page.evaluate.return_value = {"id": "0123456789abcdef01234567", "title": "上海五日游", "desc": "外滩与豫园同片区慢游，午后安排休息。"}
        note = crawler._read_xhs_detail(page, {"title": "卡片标题", "url": SIGNED}, "上海五日游")
        self.assertEqual(note["kind"], "article")
        self.assertIn("午后", note["text"])
        page.evaluate.assert_called_once()
        self.assertEqual(page.evaluate.call_args.args[1], "0123456789abcdef01234567")

    def test_initial_state_does_not_use_other_note(self):
        page = MagicMock()
        page.url = SIGNED
        page.content.return_value = '<main>详情加载中</main>'
        page.locator.return_value.count.return_value = 0
        page.evaluate.return_value = {"id": "ffffffffffffffffffffffff", "title": "其他笔记", "desc": "不应读取"}
        note = crawler._read_xhs_detail(page, {"title": "卡片标题", "url": SIGNED}, "上海五日游")
        self.assertEqual(note["kind"], "title_only")
        self.assertEqual(note["text"], "")

    def test_changed_trip_information_triggers_fresh_xhs_search(self):
        with patch.object(crawler, "search_xhs_browser", return_value=[]) as browser, \
             patch.object(crawler, "_search", return_value=[]), \
             patch.object(crawler, "_directory_guides", return_value=[]):
            crawler.collect_guides(["上海 5天 秋季 老年人 旅游攻略 site:xiaohongshu.com"], "上海")
            crawler.collect_guides(["杭州 2天 冬季 情侣 旅游攻略 site:xiaohongshu.com"], "杭州")
        self.assertEqual(browser.call_count, 2)
        self.assertIn("上海 5天 秋季 老年人", browser.call_args_list[0].args[0])
        self.assertIn("杭州 2天 冬季 情侣", browser.call_args_list[1].args[0])

    def test_title_only_records_do_not_block_alternative_evidence(self):
        note = {"title": "上海攻略", "url": SIGNED, "text": "", "kind": "title_only", "platform": "www.xiaohongshu.com"}
        with patch.object(crawler, "search_xhs_browser", return_value=[note]), \
             patch.object(crawler, "_search", return_value=[]), \
             patch.object(crawler, "_directory_guides", return_value=[]) as directory:
            notes = crawler.collect_guides(["上海五日游"], "上海")
        self.assertEqual(notes, [note])
        directory.assert_called_once_with("上海")


if __name__ == "__main__":
    unittest.main()
