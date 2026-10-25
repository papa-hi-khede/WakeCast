"""
Click-to-tweet button app (no API keys).

A small window with a "Post next tweet" button. Each click posts one tweet from
tweets.txt through a browser session that stays open in the background, so
clicks are fast.

Setup:
    pip install playwright
    playwright install chromium

Run:
    python tweet_button.py

First: double-click start_chrome.bat. It opens a normal Chrome window on x.com.
Log in there yourself (the login is remembered in ./chrome_profile, so you only do
this once) and leave that window open. Then run this script and click the button.

tweets.txt : one tweet per line (max 280 chars)
posted.txt : created automatically, remembers what was already posted

NOTE: Driving X through the browser is against X's Terms of Service and can get
the account limited or suspended. Use at your own risk, keep the pace modest
(your ~5 min clicks are fine), and post only your own content.
"""

import queue
import random
import threading
import time
import tkinter as tk
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_DIR = Path(__file__).resolve().parent  # always use the script's own folder
PROFILE_DIR = str(BASE_DIR / "x_profile")
TWEETS_FILE = BASE_DIR / "tweets.txt"
POSTED_FILE = BASE_DIR / "posted.txt"

cmd_q: "queue.Queue[tuple]" = queue.Queue()     # GUI -> worker
status_q: "queue.Queue[tuple]" = queue.Queue()  # worker -> GUI


def load_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def remaining_tweets() -> list[str]:
    posted = set(load_lines(POSTED_FILE))
    return [t for t in load_lines(TWEETS_FILE) if t not in posted and len(t) <= 280]


def post_tweet(ctx, text: str, dry_run: bool):
    page = ctx.new_page()
    try:
        page.goto("https://x.com/compose/post", wait_until="domcontentloaded")
        box = page.locator('[data-testid="tweetTextarea_0"]')
        box.wait_for(timeout=20000)
        box.click()
        page.keyboard.type(text, delay=random.randint(20, 60))
        if dry_run:
            page.wait_for_timeout(2500)
            return
        page.locator('[data-testid="tweetButton"]').click()
        page.wait_for_timeout(3500)
    finally:
        page.close()


def worker():
    """Owns all Playwright objects (they must stay on one thread)."""
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            ctx = browser.contexts[0]
            status_q.put(("info", "Connected to Chrome. Ready."))
        except Exception:
            msg = "Can't find Chrome. Double-click start_chrome.bat, log in to X, then restart this app."
            status_q.put(("error", msg))
            while True:
                cmd = cmd_q.get()
                if cmd[0] == "quit":
                    return
                status_q.put(("error", msg))

        while True:
            cmd = cmd_q.get()
            if cmd[0] == "quit":
                break
            if cmd[0] == "post":
                dry_run = cmd[1]
                pool = remaining_tweets()
                if not pool:
                    status_q.put(("error", "No unposted tweets left in tweets.txt."))
                    continue
                text = random.choice(pool)
                status_q.put(("info", "Posting..."))
                try:
                    post_tweet(ctx, text, dry_run)
                    if dry_run:
                        status_q.put(("info", f"[Dry run] typed: {text[:60]}"))
                    else:
                        with POSTED_FILE.open("a", encoding="utf-8") as f:
                            f.write(text + "\n")
                        status_q.put(("posted", text))
                except PWTimeout:
                    status_q.put(("error", "Timed out. Are you logged in to X?"))
                except Exception as e:
                    status_q.put(("error", f"Failed: {e}"))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.last_post_time: float | None = None
        self.busy = False

        root.title("Tweet Button")
        root.geometry("420x260")
        root.attributes("-topmost", True)

        self.btn = tk.Button(
            root, text="Post next tweet", font=("Segoe UI", 16, "bold"),
            height=2, command=self.on_click,
        )
        self.btn.pack(fill="x", padx=16, pady=(16, 8))

        self.dry = tk.BooleanVar(value=False)
        tk.Checkbutton(root, text="Dry run (type but don't post)", variable=self.dry).pack()

        self.status = tk.Label(root, text="Starting browser...", wraplength=380, justify="left")
        self.status.pack(padx=16, pady=(10, 2), anchor="w")

        self.since = tk.Label(root, text="", fg="gray")
        self.since.pack(padx=16, anchor="w")

        self.left = tk.Label(root, text="", fg="gray")
        self.left.pack(padx=16, anchor="w")

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.refresh_left()
        self.poll()

    def refresh_left(self):
        self.left.config(text=f"Tweets remaining: {len(remaining_tweets())}")

    def on_click(self):
        if self.busy:
            return
        self.busy = True
        self.btn.config(state="disabled")
        cmd_q.put(("post", self.dry.get()))

    def poll(self):
        try:
            while True:
                kind, msg = status_q.get_nowait()
                if kind == "posted":
                    self.last_post_time = time.time()
                    self.status.config(text=f"Posted: {msg[:80]}", fg="green")
                    self.busy = False
                    self.btn.config(state="normal")
                elif kind == "error":
                    self.status.config(text=msg, fg="red")
                    self.busy = False
                    self.btn.config(state="normal")
                else:
                    self.status.config(text=msg, fg="black")
                    if msg.startswith("[Dry run]") or msg.startswith("Ready"):
                        self.busy = False
                        self.btn.config(state="normal")
                self.refresh_left()
        except queue.Empty:
            pass

        if self.last_post_time:
            mins = int((time.time() - self.last_post_time) // 60)
            secs = int((time.time() - self.last_post_time) % 60)
            self.since.config(text=f"Last post: {mins}m {secs}s ago")

        self.root.after(500, self.poll)

    def on_close(self):
        cmd_q.put(("quit",))
        self.root.after(800, self.root.destroy)


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    root = tk.Tk()
    App(root)
    root.mainloop()
