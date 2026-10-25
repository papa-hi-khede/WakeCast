"""
WakeCast server: the one program that ties everything together (no window, no API keys).

What it does:
  1. Serves the alarm page at http://127.0.0.1:5005 and opens it in your browser.
  2. When Snooze is pressed on that page, posts one tweet using the same
     posting steps as tweet_button.py (imported, not copied).
  3. Checks that Chrome is open and X is logged in, and tells the alarm page.

Keep this file in the same folder as tweet_button.py, tweets.txt, posted.txt,
start_chrome.bat and alarm_snooze.html.

Start everything by double-clicking start_all.bat.
(Or: run start_chrome.bat, log in to X once, then `python tweet_server.py`.)
Use `python tweet_server.py --no-browser` to skip opening the alarm page.
"""

import queue
import random
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import tweet_button as tb  # reuses load_lines, remaining_tweets, file paths

HOST, PORT = "127.0.0.1", 5005
CDP_URL = "http://localhost:9222"
ALARM_FILE = tb.BASE_DIR / "alarm_snooze.html"
MAX_PENDING = 3  # safety: never queue up a pile of tweets
RECHECK_LOGGED_OUT_AFTER = 60  # seconds before re-checking X while it looks logged out

# Only this page (served from this server) may talk to the server. This stops
# other websites open in your browser from triggering tweets.
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ALLOWED_ORIGINS = {f"http://{h}" for h in ALLOWED_HOSTS}

jobs: "queue.Queue[str]" = queue.Queue()
lock = threading.Lock()
x_check_queued = False
state = {"x": None, "at": 0.0}  # x: None (unknown) | "ok" | "logged-out"
last_text = None


def log(msg: str):
    print(time.strftime("[%H:%M:%S]"), msg, flush=True)


def chrome_reachable() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 9222), timeout=0.5):
            return True
    except OSError:
        return False


def queue_x_check():
    global x_check_queued
    with lock:
        if x_check_queued:
            return
        x_check_queued = True
    jobs.put("check")


def status_text() -> str:
    if not chrome_reachable():
        return "chrome-missing"
    stale = state["x"] == "logged-out" and time.time() - state["at"] > RECHECK_LOGGED_OUT_AFTER
    if state["x"] is None or stale:
        queue_x_check()
        return "x-checking" if state["x"] is None else "x-logged-out"
    return "x-logged-out" if state["x"] == "logged-out" else "ready"


def pick_tweet():
    """Unposted tweet first. When all are used, reuse any tweet (not the same one twice in a row)."""
    pool = tb.remaining_tweets()
    fresh = bool(pool)
    if not pool:
        pool = [t for t in tb.load_lines(tb.TWEETS_FILE) if len(t) <= 280]
        if len(pool) > 1 and last_text in pool:
            pool = [t for t in pool if t != last_text]
    if not pool:
        return None, False
    return random.choice(pool), fresh


def check_x(ctx):
    """Open x.com/home briefly and see whether the logged-in sidebar appears."""
    page = ctx.new_page()
    try:
        page.goto("https://x.com/home", wait_until="domcontentloaded")
        try:
            page.locator('[data-testid="SideNav_AccountSwitcher_Button"]').first.wait_for(timeout=12000)
            state["x"] = "ok"
            log("X login check: logged in.")
        except PWTimeout:
            state["x"] = "logged-out"
            log("X login check: does not look logged in. Log in to X in the Chrome window.")
        state["at"] = time.time()
    finally:
        page.close()


def post_tweet(ctx, text: str):
    """Same steps as tweet_button.post_tweet, but X now has TWO compose boxes on
    /compose/post (the popup and the home feed behind it), so we work inside the popup."""
    page = ctx.new_page()
    try:
        page.goto("https://x.com/compose/post", wait_until="domcontentloaded")
        scope = page
        try:
            dialog = page.locator('[role="dialog"]').first
            dialog.wait_for(timeout=15000)
            scope = dialog
        except PWTimeout:
            pass  # no popup found: fall back to the whole page
        box = scope.locator('[data-testid="tweetTextarea_0"]').first
        box.wait_for(timeout=20000)
        box.click()
        page.keyboard.type(text, delay=random.randint(20, 60))
        scope.locator('[data-testid="tweetButton"]').first.click()
        page.wait_for_timeout(3500)
    finally:
        page.close()


def worker():
    """Owns all Playwright objects (they must stay on one thread)."""
    global last_text, x_check_queued
    with sync_playwright() as p:
        ctx = None
        while True:
            job = jobs.get()
            try:
                if ctx is None:
                    browser = p.chromium.connect_over_cdp(CDP_URL)
                    ctx = browser.contexts[0]
                    log("Connected to Chrome.")
                if job == "check":
                    check_x(ctx)
                    continue
                text, fresh = pick_tweet()
                if not text:
                    log("tweets.txt has no usable tweets.")
                    continue
                log(f"Posting: {text[:70]}")
                post_tweet(ctx, text)
                if fresh:
                    with tb.POSTED_FILE.open("a", encoding="utf-8") as f:
                        f.write(text + "\n")
                last_text = text
                log("Posted.")
            except Exception as e:
                ctx = None  # reconnect on the next job
                if job == "post":
                    state["x"] = None  # re-check the X login after a failed tweet
                    log(f"Tweet failed (alarm is not affected): {e}")
                else:
                    log(f"Could not check X login: {e}")
            finally:
                if job == "check":
                    with lock:
                        x_check_queued = False


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: str = "", ctype: str = "text/plain; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _allowed(self) -> bool:
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if host not in ALLOWED_HOSTS:
            return False
        return origin is None or origin in ALLOWED_ORIGINS

    def do_GET(self):
        if not self._allowed():
            self._send(403, "forbidden")
        elif self.path in ("/", "/alarm", "/index.html"):
            if ALARM_FILE.exists():
                self._send(200, ALARM_FILE.read_text(encoding="utf-8"), "text/html; charset=utf-8")
            else:
                self._send(404, "alarm_snooze.html not found next to tweet_server.py")
        elif self.path.startswith("/status"):
            self._send(200, status_text())
        else:
            self._send(404, "not found")

    def do_POST(self):
        if not self._allowed():
            self._send(403, "forbidden")
        elif self.path.startswith("/tweet"):
            if jobs.qsize() >= MAX_PENDING:
                self._send(429, "busy")
                return
            jobs.put("post")
            self._send(202, "queued")  # reply instantly so snooze is never delayed
        else:
            self._send(404, "not found")

    def log_message(self, *args):
        pass  # keep the console clean


if __name__ == "__main__":
    url = f"http://{HOST}:{PORT}/"
    threading.Thread(target=worker, daemon=True).start()
    log(f"WakeCast is running at {url}  (Ctrl+C to stop)")
    if not ALARM_FILE.exists():
        log("WARNING: alarm_snooze.html is missing from this folder.")
    if not chrome_reachable():
        log("Chrome is not open yet. Run start_chrome.bat and log in to X.")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        log("Stopped.")
