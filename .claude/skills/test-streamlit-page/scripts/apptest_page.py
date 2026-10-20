"""Drive one Streamlit page headlessly with AppTest and print what it rendered.

Run from the repo root with the project venv:

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe \
        .claude/skills/test-streamlit-page/scripts/apptest_page.py "Labs/Lab 5/Lab5.py" \
        --text "City=Lima, Peru" --click "Get advice"

Every key in .streamlit/secrets.toml is injected, so pages make their real
API calls. Actions run in the order given; each --click and --chat triggers a
rerun and a report. Exit code is 1 if the page raised an exception.
"""

import argparse
import os
import sys
import time
import tomllib

from streamlit.testing.v1 import AppTest


def pair(value):
    label, sep, rest = value.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError(f"expected Label=value, got {value!r}")
    return label.strip(), rest


def find(widgets, label, kind):
    for widget in widgets:
        if widget.label == label:
            return widget
    labels = [w.label for w in widgets]
    sys.exit(f"No {kind} labelled {label!r}. Found: {labels}")


def report(at, step, elapsed):
    print("=" * 72)
    print(f"{step}  ({elapsed:.1f}s)")
    rows = {
        "exceptions": [e.value for e in at.exception],
        "errors": [e.value for e in at.error],
        "warnings": [e.value for e in at.warning],
        "info": [e.value for e in at.info],
        "subheaders": [s.value for s in at.subheader],
        "captions": [c.value for c in at.main.caption],
        "metrics": [(m.label, m.value, m.delta) for m in at.metric],
    }
    for name, values in rows.items():
        if values:
            print(f"{name}: {values}")
    in_chat = set()
    for message in at.chat_message:
        texts = [md.value for md in message.markdown]
        in_chat.update(texts)
        print(f"--- chat [{message.name}]\n" + "\n".join(texts))
    for md in at.main.markdown:
        if md.value not in in_chat:
            print(f"--- markdown\n{md.value}")
    if len(at.json):
        print(f"json blocks: {len(at.json)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("page", help="page file, relative to the repo root")
    parser.add_argument("--text", type=pair, action="append", default=[],
                        metavar="LABEL=VALUE", help="fill a text_input / text_area")
    parser.add_argument("--select", type=pair, action="append", default=[],
                        metavar="LABEL=OPTION", help="pick a selectbox option (sidebar too)")
    parser.add_argument("--click", action="append", default=[], metavar="LABEL",
                        help="click a button or form submit button, then rerun")
    parser.add_argument("--chat", action="append", default=[], metavar="MESSAGE",
                        help="send a chat_input message, then rerun (repeat for a conversation)")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()

    # AppTest resolves relative paths against this script, not the CWD.
    page = os.path.abspath(args.page)
    at = AppTest.from_file(page, default_timeout=args.timeout)
    secrets_path = os.path.join(".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        with open(secrets_path, "rb") as f:
            for key, value in tomllib.load(f).items():
                at.secrets[key] = value
    else:
        print("note: no .streamlit/secrets.toml here; run from the repo root")

    start = time.time()
    at.run()
    report(at, f"LOAD {args.page}", time.time() - start)

    for label, option in args.select:
        find(at.selectbox, label, "selectbox").select(option)
    for label, value in args.text:
        widgets = list(at.text_input) + list(at.text_area)
        find(widgets, label, "text input").input(value)

    steps = [("click", c) for c in args.click] + [("chat", m) for m in args.chat]
    if not steps and (args.select or args.text):
        steps = [("rerun", "")]
    for kind, value in steps:
        start = time.time()
        if kind == "click":
            find(at.button, value, "button").click().run()
        elif kind == "chat":
            at.chat_input[0].set_value(value).run()
        else:
            at.run()
        report(at, f"{kind.upper()} {value!r}", time.time() - start)

    sys.exit(1 if len(at.exception) else 0)


if __name__ == "__main__":
    main()
