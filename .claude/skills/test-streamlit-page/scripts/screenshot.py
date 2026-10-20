"""Open a Streamlit app in real Chrome, interact with it, and screenshot it.

Local (starts its own server on a free port, stops it afterwards):

    .venv/Scripts/python.exe .claude/skills/test-streamlit-page/scripts/screenshot.py \
        --app Labs/streamlit_app.py --page Lab5 \
        --text "City=Syracuse, NY" --click "Get advice" --out lab5.png

Live Streamlit Cloud app (wakes it if asleep; --expect retries until a fresh
deploy shows the text, so it doubles as the post-push check):

    ... screenshot.py --url https://su-mahcai-ist-688-building-hc-apps.streamlit.app/ \
        --expect "What to Wear" --text "City=Syracuse, NY" --click "Get advice" --out live.png

Exit code is 1 if the page shows a Streamlit exception or --expect never appears.
"""

import argparse
import socket
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

WAKE_BUTTON = "Yes, get this app back up!"


def pair(value):
    label, sep, rest = value.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError(f"expected Label=value, got {value!r}")
    return label.strip(), rest


def start_server(app):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", app,
         "--server.headless", "true", "--server.port", str(port),
         "--browser.gatherUsageStats", "false"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://localhost:{port}/_stcore/health", timeout=2)
            return proc, f"http://localhost:{port}/"
        except OSError:
            time.sleep(1)
    proc.terminate()
    sys.exit(f"streamlit did not start for {app}")


def app_frame(page):
    """Streamlit Cloud serves the app inside an iframe; locally it is the page."""
    for frame in page.frames:
        if frame.locator('[data-testid="stApp"]').count():
            return frame
    return None


def settle(frame, timeout):
    """Wait for the script run that the last action triggered to finish."""
    frame.wait_for_timeout(1500)
    frame.locator('[data-testid="stStatusWidget"]').wait_for(state="hidden", timeout=timeout)
    frame.wait_for_timeout(1000)


def open_app(page, url, expect, retries, timeout):
    for attempt in range(retries):
        page.goto(url, timeout=90_000)
        page.wait_for_timeout(6000)
        for frame in page.frames:
            wake = frame.get_by_role("button", name=WAKE_BUTTON)
            if wake.count():
                print("app was asleep; waking it")
                wake.click()
                page.wait_for_timeout(60_000)
                break
        frame = app_frame(page)
        if frame:
            settle(frame, timeout)
            if not expect or frame.get_by_text(expect).count():
                return frame
        print(f"attempt {attempt + 1}/{retries}: "
              f"{'app not loaded' if not frame else repr(expect) + ' not visible yet'}")
        page.wait_for_timeout(20_000)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--app", help="entry point to serve locally, e.g. Labs/streamlit_app.py")
    target.add_argument("--url", help="already-running app, e.g. the Streamlit Cloud URL")
    parser.add_argument("--page", default="", help="page URL path, e.g. Lab5 or HW5")
    parser.add_argument("--expect", help="text that must appear before interacting")
    parser.add_argument("--retries", type=int, default=1,
                        help="page loads to try while waiting for --expect (use ~8 after a push)")
    parser.add_argument("--text", type=pair, action="append", default=[], metavar="LABEL=VALUE")
    parser.add_argument("--click", action="append", default=[], metavar="LABEL")
    parser.add_argument("--chat", action="append", default=[], metavar="MESSAGE")
    parser.add_argument("--out", default="screenshot.png")
    parser.add_argument("--full-page", action="store_true")
    parser.add_argument("--channel", default="chrome", help="installed browser: chrome or msedge")
    parser.add_argument("--timeout", type=float, default=180, help="seconds per script run")
    args = parser.parse_args()

    proc, base = start_server(args.app) if args.app else (None, args.url)
    url = base.rstrip("/") + "/" + args.page
    timeout = args.timeout * 1000
    failed = False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel=args.channel)
            page = browser.new_page(viewport={"width": 1280, "height": 900},
                                    device_scale_factor=1.5)
            frame = open_app(page, url, args.expect, args.retries, timeout)
            if frame is None:
                page.screenshot(path=args.out)
                sys.exit(f"FAILED: app or {args.expect!r} never appeared at {url}; "
                         f"screenshot in {args.out}")

            for label, value in args.text:
                frame.get_by_label(label, exact=True).fill(value)
            for label in args.click:
                frame.get_by_role("button", name=label, exact=True).click()
                settle(frame, timeout)
            for message in args.chat:
                box = frame.get_by_test_id("stChatInputTextArea")
                box.fill(message)
                box.press("Enter")
                settle(frame, timeout)

            exceptions = frame.locator('[data-testid="stException"]').count()
            errors = frame.locator('[data-testid="stAlertContentError"]').all_inner_texts()
            page.screenshot(path=args.out, full_page=args.full_page)
            print(f"url: {url}")
            print(f"screenshot: {args.out}")
            print(f"exceptions: {exceptions}")
            if errors:
                print(f"error alerts: {errors}")
            body = frame.locator('[data-testid="stMain"]').first.inner_text()
            print("--- visible text (first 1500 chars)\n" + body[:1500])
            failed = exceptions > 0
            browser.close()
    finally:
        if proc:
            proc.terminate()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
