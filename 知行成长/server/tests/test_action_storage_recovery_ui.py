"""Actual action editor against disposable PostgreSQL/HTTP fixtures only."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
import uuid

from playwright.sync_api import expect, sync_playwright


class ActionStorageRecoveryUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.getenv("TEST_LEGACY_PG_DSN"):
            raise RuntimeError("Provide an explicitly isolated TEST_LEGACY_PG_DSN")
        cls.fixture = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("serve_daily_arrangements_fixture.py"))],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=os.environ.copy(),
        )
        cls.addClassCleanup(cls.stop_fixture)
        if not select.select([cls.fixture.stdout], [], [], 30)[0]:
            raise RuntimeError("Fixture startup timeout")
        line = cls.fixture.stdout.readline()
        if not line:
            raise RuntimeError(cls.fixture.stderr.read())
        cls.base = json.loads(line)["url"]
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(
            headless=True, executable_path=os.getenv("CHROME_EXECUTABLE", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        )
        cls.addClassCleanup(cls.browser.close)

    @classmethod
    def stop_fixture(cls):
        cls.fixture.terminate()
        try:
            cls.fixture.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.fixture.kill()
            cls.fixture.wait(timeout=5)
        cls.fixture.stdout.close()
        cls.fixture.stderr.close()

    def setUp(self):
        self.context = self.browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 1000})
        self.addCleanup(self.context.close)
        self.context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(self.base + "/") else route.abort())
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.evidence = Path(os.getenv("ACTION_STORAGE_EVIDENCE_DIR", "/tmp/grow-web-batch1-evidence/w01"))
        self.evidence.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def ready(self):
        self.page.goto(self.base)
        expect(self.page.locator("#agendaList")).not_to_contain_text("正在读取安排")

    def editor(self):
        self.page.locator("#view-personal .day-actions").get_by_role("button", name="添加行动", exact=True).click()
        return self.page.get_by_role("dialog")

    def test_form_warning_download_import_and_same_key_recovery_after_reload(self):
        self.context.add_init_script("""const original=Storage.prototype.setItem;Storage.prototype.setItem=function(key,value){
          if(key.startsWith('grow.actions.'))throw new DOMException('synthetic quota','QuotaExceededError');
          return original.call(this,key,value);
        };""")
        self.ready()
        expect(self.page.locator("#actionRecovery")).to_contain_text("浏览器空间不足")
        dialog = self.editor()
        title = "网页恢复验收-" + uuid.uuid4().hex[:8]
        dialog.get_by_label("做什么", exact=True).fill(title)
        expect(dialog.locator(".action-recovery-warning")).to_contain_text("刷新或关闭前请下载副本")
        self.context.request.post(self.base + "/fixture/drop-next")
        dialog.get_by_role("button", name="加入今日", exact=True).click()
        expect(dialog.get_by_role("alert")).to_contain_text("响应丢失")
        with tempfile.TemporaryDirectory(prefix="grow-ui-action-recovery-") as temp:
            with self.page.expect_download() as downloaded:
                dialog.get_by_role("button", name="下载行动草稿副本", exact=True).click()
            filename = Path(temp) / "recovery.json"
            downloaded.value.save_as(filename)
            bundle = json.loads(filename.read_text())
            pending = next(value for key, value in bundle["entries"].items() if key.startswith("pending."))
            original_key = pending["body"]["key"]
            self.page.screenshot(path=str(self.evidence / "form-storage-warning.png"))
            dialog.get_by_role("button", name="稍后继续", exact=True).click()
            leaving = []
            def accept_leave(event):
                leaving.append(event.type)
                event.accept()
            self.page.on("dialog", accept_leave)
            self.page.reload()
            self.assertIn("beforeunload", leaving, "unsaved page data must warn before refresh")
            expect(self.page.locator("#agendaList")).not_to_contain_text("正在读取安排")
            self.page.locator("#actionRecovery summary").click()
            self.page.locator("#actionRecovery input[type=file]").set_input_files(filename)
            expect(self.page.locator("#actionRecovery")).to_contain_text("已恢复行动草稿和待确认请求")
            expect(self.page.locator("#actionRecovery")).to_contain_text("浏览器空间不足")
            dialog = self.editor()
            expect(dialog.get_by_label("做什么", exact=True)).to_have_value(title)
            with self.page.expect_request(lambda request: request.method == "POST" and request.url == self.base + "/api/action-plans") as retried:
                dialog.get_by_role("button", name="重试原提交", exact=True).click()
            self.assertEqual(retried.value.post_data_json["key"], original_key)
            expect(dialog).to_have_count(0)
        plans = self.context.request.get(self.base + "/api/action-plans").json()["plans"]
        self.assertEqual(len([plan for plan in plans if plan["title"] == title]), 1)
        self.page.screenshot(path=str(self.evidence / "form-storage-recovered.png"))

    def test_storage_getter_security_error_still_initializes_action_editor(self):
        self.context.add_init_script("""Object.defineProperty(window,'localStorage',{get(){throw new DOMException('synthetic denied getter','SecurityError');}});""")
        self.ready()
        expect(self.page.locator("#actionRecovery")).to_contain_text("浏览器存储不可用")
        dialog = self.editor()
        dialog.get_by_label("做什么", exact=True).fill("getter denied keeps editable")
        expect(dialog.locator(".action-recovery-warning")).to_contain_text("浏览器无法保存")
        with self.page.expect_download() as downloaded:
            dialog.get_by_role("button", name="下载行动草稿副本", exact=True).click()
        self.assertTrue(downloaded.value.suggested_filename.startswith("grow-action-drafts-"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
