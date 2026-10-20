# HW evaluation format

`HW/HW4_Evaluation.txt` is the model to follow. Read it before writing.

Files, all in `HW/`:
- `HWN_Evaluation.txt`: the Blackboard submission.
  - Plain text, wrapped at about 78 columns.
  - Section headings in ALL CAPS, numbered to match the handout's parts (`5a. THE FIVE QUESTIONS`).
- `HWN_Evaluation.md`: the same content with Markdown headings. Can run longer.
- `HWN_transcripts.md`: the raw question-and-answer transcripts, one `##` section per model run.

Layout of the `.txt`:
1. Title line, then `Shahaan Khan (szkhan@syr.edu)`.
2. `App:`, `Code:` and the companion file names.
3. SETUP: what was built and why each choice was made (chunking, database, models, memory).
4. The handout's evaluation parts, in order. For each test question, say what it probes. Then give a results table (question × model) and one paragraph per notable result.
5. WOULD I CHANGE ANYTHING?: a concrete change, ideally one already tested, and why it was left out of the submitted app.
6. MODEL CHOICE, then NOTES: how the tests were run (through the real app via AppTest), the requirements.txt status, and the live-app check.

Evidence rules:
- Every number (timings, distances, counts) comes from a run you made in this session. Re-measure rather than recall it; HW 4 needed a correction commit for timing figures.
- Run the questions through the real page with `test-streamlit-page`, so the answers reflect the same prompt, retrieval and memory a user gets.
- Report failures plainly, with the cause you found.
