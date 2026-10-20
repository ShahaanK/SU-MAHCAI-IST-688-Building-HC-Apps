---
name: ship-hw
description: Build, test, push and verify a course HW/Lab Streamlit app
---

1. **Build** the page with `new-lab`.
2. **Verify** it with `test-streamlit-page`: every requirement on every branch, plus a local screenshot.
3. **HW only: write the evaluation** following [`EVALUATION.md`](EVALUATION.md), then run the humanizer skill on it.
4. **Confirm the deploy branch** before pushing; don't assume `main`.
   - Labs app (`su-mahcai-ist-688-building-hc-apps.streamlit.app`) deploys from **`Labs`**, using `Labs/streamlit_app.py`.
   - HW Manager (`...-hw-manager.streamlit.app`): HW work reaches it by a PR from `HW` into `main`. If unsure, ask the user for the app's deploy log; its first line names the branch.
5. **Commit.**
   - Stage explicit paths (`git add -- <files>`). `HW/HW4-ChromaDB/` is untracked on `Labs` and stays out.
   - Message style: `Add Lab N: <what it is>` or `Add HW N: ...`. End the message with the body; no AI attribution.
6. **Push.** Push to the deploy branch, or `gh pr create` into it. If a merge is blocked, give the user the exact PR link to merge.
   - For a second branch checkout, make worktrees under `C:\dev`. The temp folder path is too long for this repo's syllabus PDFs.
7. **Check the live app** with `test-streamlit-page`'s `screenshot.py --url ... --expect "<page title>" --retries 8`. Done when it shows the new page answering a real request.
8. **Report** the Blackboard upload: the file path and the app link.
