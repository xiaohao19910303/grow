"""Chrome transport recovery with a disposable localhost fake, never a business DB.

This exercises the actual browser client and a fresh page, not the production UI.
The fake service commits each key once and can lose its response after commit.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

from playwright.sync_api import sync_playwright


CLIENT = Path(__file__).resolve().parents[1] / "static/action-plan-client.js"
FORM = {"flow": "create-day", "origin_key": "browser-fixture", "parent_context": None, "entry_date": "2026-10-22"}


class ActionStorageRecoveryBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(
            headless=True,
            executable_path=os.getenv("CHROME_EXECUTABLE", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        )
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.saved = {}
        self.calls = []
        self.drop_response = True
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def reply(self, status, data, kind="application/json"):
                raw = data if isinstance(data, bytes) else json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/client.js":
                    return self.reply(200, CLIENT.read_bytes(), "text/javascript;charset=utf-8")
                if self.path.startswith("/api/action-plans/requests/"):
                    return self.reply(200, {"found": False})
                if self.path == "/":
                    return self.reply(200, b'''<!doctype html><meta charset="utf-8">
                    <button id="download">Download recovery copy</button>
                    <script src="/client.js"></script><script>
                    window.client=ActionPlanClient.create({account:'chrome-storage-fixture',storage:localStorage,request:fetch});
                    document.querySelector('#download').onclick=()=>{
                      const blob=new Blob([JSON.stringify(client.exportRecovery())],{type:'application/json'});
                      const link=document.createElement('a');link.href=URL.createObjectURL(blob);
                      link.download='action-recovery.json';link.click();URL.revokeObjectURL(link.href);
                    };
                    </script>''', "text/html;charset=utf-8")
                self.reply(404, {})

            def do_POST(self):
                if self.path != "/api/action-plans":
                    return self.reply(404, {})
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                owner.calls.append(body)
                owner.saved.setdefault(body["key"], {"plans": [{"id": "fixture-plan"}]})
                if owner.drop_response:
                    return self.reply(503, {"message": "synthetic response lost after commit"})
                self.reply(200, owner.saved[body["key"]])

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = "http://127.0.0.1:" + str(self.server.server_port)
        self.context = self.browser.new_context(accept_downloads=True)
        self.addCleanup(self.context.close)
        self.context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(self.base + "/") else route.abort())
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def check_failed_storage(self, error_name, reason):
        self.context.add_init_script(f"""Storage.prototype.setItem=function(){{throw new DOMException('synthetic denied write', {json.dumps(error_name)});}};""")
        self.page.goto(self.base)
        draft = self.page.evaluate("context => client.newDraft(context,{title:'refresh recovery text'})", FORM)
        result = self.page.evaluate("""async id=>{
          try { await client.write('draft:'+id,'',{title:'refresh recovery text'}); }
          catch(error){return error.message;}
        }""", draft["draft_id"])
        self.assertIn("response lost", result)
        original_key = self.calls[-1]["key"]
        status = self.page.evaluate("client.storageStatus()")
        self.assertFalse(status["durable"])
        self.assertEqual(status["reason"], reason)
        with self.page.expect_download() as download:
            self.page.locator("#download").click()
        with tempfile.TemporaryDirectory(prefix="grow-action-recovery-") as temp:
            target = Path(temp) / "recovery.json"
            download.value.save_as(target)
            bundle = json.loads(target.read_text())
        self.assertIn(original_key, json.dumps(bundle))
        self.page.reload()
        self.assertEqual(self.page.evaluate("context=>client.listDrafts(context)", FORM), [])
        self.page.evaluate("bundle=>client.importRecovery(bundle)", bundle)
        restored = self.page.evaluate("id=>client.pending('draft:'+id)", draft["draft_id"])
        self.assertEqual(restored["key"], original_key)
        self.assertEqual(self.page.evaluate("context=>client.listDrafts(context)[0].values.title", FORM), "refresh recovery text")
        found = self.page.evaluate("id=>client.resolvePending('draft:'+id)", draft["draft_id"])
        self.assertFalse(found["found"])
        self.drop_response = False
        self.page.evaluate("id=>client.retryPending('draft:'+id,'')", draft["draft_id"])
        self.assertEqual(self.calls[-1]["key"], original_key)
        self.assertEqual(len(self.saved), 1)

    def test_quota_recovery_download_reload_and_same_key_retry(self):
        self.check_failed_storage("QuotaExceededError", "quota")

    def test_security_recovery_download_reload_and_same_key_retry(self):
        self.check_failed_storage("SecurityError", "unavailable")

    def test_shared_browser_storage_observes_other_page_edits_and_deletions(self):
        self.page.goto(self.base)
        draft=self.page.evaluate("context=>client.newDraft(context,{title:'first page draft'})",FORM)
        second=self.context.new_page()
        second.goto(self.base)
        self.assertEqual(second.evaluate("context=>client.listDrafts(context)[0].values.title",FORM),"first page draft")
        self.page.evaluate("draft=>client.saveDraft(draft,{title:'first page updated'})",draft)
        self.assertEqual(second.evaluate("context=>client.listDrafts(context)[0].values.title",FORM),"first page updated")
        second.evaluate("id=>client.deleteDraft(id)",draft["draft_id"])
        self.assertEqual(self.page.evaluate("context=>client.listDrafts(context)",FORM),[])
        self.page.evaluate("id=>client.deleteDraft(id)",draft["draft_id"])
        second.evaluate("draft=>{client.put('draft.'+draft.draft_id,{...draft,values:{title:'same id recreated'}});client.put('draft.index',[draft.draft_id]);}",draft)
        self.assertEqual(self.page.evaluate("context=>client.listDrafts(context)[0].values.title",FORM),"same id recreated")


if __name__ == "__main__":
    unittest.main(verbosity=2)
