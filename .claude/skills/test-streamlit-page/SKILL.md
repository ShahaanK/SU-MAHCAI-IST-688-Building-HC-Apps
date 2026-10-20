---
name: test-streamlit-page
description: Verify a Lab or HW Streamlit page end to end. Use when checking a page works before shipping, screenshotting it, or confirming the live Streamlit Cloud app after a push.
---

Two scripts in `scripts/`, both run from the repo root with the project venv and `PYTHONIOENCODING=utf-8`. Each prints what the page rendered and exits 1 on a Streamlit exception. `--help` lists every flag.

1. **`apptest_page.py <page>`** drives a single page headlessly with real API calls, injecting every key from `.streamlit/secrets.toml`. Use `--text "Label=value"`, `--select "Label=option"`, `--click "Label"` and `--chat "message"`; repeat `--chat` for a conversation. Run one invocation per input case.
2. **`screenshot.py`** drives real Chrome. Pass `--app <entry point> --page <url path>` to start a local server on a free port, or `--url <live app>` for Streamlit Cloud. With `--url`, it wakes a sleeping app, and `--expect "<text>" --retries 8` waits out a redeploy. Read the PNG it writes to see what a user sees.

Done means every requirement in the assignment has been exercised, through every branch the page has:
- the happy path on each model in the sidebar
- defaults (for example, a blank input)
- bad input that should show an error
- input the LLM should handle without a tool
- a multi-turn follow-up, for pages with memory

Then take one local screenshot, and after pushing, one live check.

Gotchas:
- An exception page means read the cause line first. `RateLimitError: insufficient_quota` / `credit_balance_exhausted` means the OpenAI account is out of credits; the code isn't at fault. Tell the user, since the live apps share the key.
- AppTest prints Streamlit tracebacks to stderr, so the report lines are the summary.
- Widget labels must match exactly. The scripts list the labels they found when one is missing.
- External data sources return surprises a unit test misses. For example, wttr.in names neighborhoods ("Galeville" for Syracuse). Look at the screenshot, not just the exit code.
