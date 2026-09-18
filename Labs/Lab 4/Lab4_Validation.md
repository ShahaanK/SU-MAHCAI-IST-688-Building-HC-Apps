# Lab 4 — vector database validation

This records the Part A test before the test code was removed from `Lab4.py`
(Part B, step 4). Everything below was produced by running the shipped
`Lab4.py` headlessly with `streamlit.testing.v1.AppTest`, so the numbers come
from the same code path the app uses.

## Collection

| | |
| --- | --- |
| Collection | `Lab4Collection` |
| Embeddings | `text-embedding-3-small` (OpenAI) |
| Source | the 7 PDFs in `Lab-04-Data/` |
| Key | filename — chunk ids are `<filename>::<n>`, and every chunk carries `filename` in its metadata |
| Indexed | 7 syllabi, 41 chunks |
| Session state | `st.session_state.Lab4_VectorDB`, built only when absent |

Distances are Chroma's default L2 over OpenAI embeddings, so **lower is
closer** and the useful signal is the ordering, not the absolute value.

## Part A results

Each search returns the three closest syllabi.

### "Generative AI"

1. `IST 488 Syllabus - Building Human-Centered AI Applications.pdf` — 1.0948
2. `IST 314 Syllabus - Interacting with AI.pdf` — 1.2434
3. `IST 343 Syllabus - Data in Society.pdf` — 1.5089

Correct. The two AI courses come back first, and the gap to third place (1.24
→ 1.51) matches the fact that only two of these seven courses are actually
about AI. IST 343 (Data in Society) is a reasonable third — it covers the
social consequences of algorithms.

### "Text Mining"

1. `IST 387 Syllabus - Introduction to Applied Data Science.pdf` — 1.3254
2. `IST 418 Syllabus - Big Data Analytics.pdf` — 1.4591
3. `IST 256 Syllabus - Intro to Python for the Information Profession.pdf` — 1.4755

Correct, and worth noting that no syllabus in this set teaches text mining as
a named topic. The three returned are the three that come closest to it —
applied data science, big data analytics, and the Python course that teaches
the tooling. Distances are all high (1.33–1.48), which is the honest signal
for a query the corpus does not really cover.

### "Data Science Overview"

1. `IST 387 Syllabus - Introduction to Applied Data Science.pdf` — 1.0158
2. `IST 418 Syllabus - Big Data Analytics.pdf` — 1.0368
3. `IST 343 Syllabus - Data in Society.pdf` — 1.1444

Correct, and the best-matched query of the three. The intro applied data
science course ranks first, big data analytics second, data in society third —
which is the order a person would put them in.

## Why the documents are chunked

The first version embedded one vector per whole syllabus, which is the obvious
reading of the assignment. It ranked the three test strings acceptably but
failed badly on a real question: **"Which course teaches Python, and what are
its prerequisites?"** returned IST 387, IST 418, and IST 314 — and *not*
IST 256, *Intro to Python for the Information Profession*, the one course in
the set that is literally about Python. A single embedding averaged over 17
pages dilutes the topic past the point of being useful.

Chunking at ~2,000 characters fixed it outright:

| Query | Whole-document | Chunked |
| --- | --- | --- |
| "Which course teaches Python…" | IST 256 not in top 3 | IST 256 first, at 0.978 |
| "Generative AI" | 1.2833 | 1.0948 |
| "Text Mining" | 1.4707 | 1.3254 |
| "Data Science Overview" | 1.1564 | 1.0158 |

Every distance improved and the ranked set for the three official test strings
stayed sensible. Retrieval matches chunks, but the prompt receives the whole
syllabus the winning chunk came from, so an answer is never cut off just
because the closest chunk stopped a paragraph short.

## Why course codes get a lexical assist

Chunking still could not answer **"What is the attendance policy in IST 488?"**
Every syllabus carries near-identical policy boilerplate, so all seven scored
within 0.21 of each other and IST 488 landed *fifth*:

```
1. IST 195  0.8750      5. IST 488  1.0548
2. IST 343  0.9511      6. IST 314  1.0806
3. IST 256  1.0037      7. IST 418  1.0826
4. IST 387  1.0305
```

Raising `TOP_K` to 5 would technically reach it, but that means putting five
of seven documents into every prompt — barely retrieval at all. Instead,
`search()` detects course codes in the question and moves those syllabi to the
front. It is a no-op for any question that names no course, including all
three official test strings, so the Part A results above are unaffected.

## Part B spot checks

| Question | Retrieved first | Answer opened with |
| --- | --- | --- |
| "Which course teaches Python, and what are its prerequisites?" | IST 256 (0.981) | "From the course syllabi: IST256 and IST418" |
| "What is the attendance policy in IST 488?" | IST 488 (named in question) | "From the course syllabi: IST 488" |
| "What is the capital of France?" | IST 256 (1.740 — nothing relevant) | "Not in the course syllabi - answering from general knowledge" |

The disclosure requirement works in both directions: the bot names the syllabi
when it uses them, and says plainly when it is answering from general
knowledge instead. On the IST 488 question it also reported what the syllabus
does *not* say — there is no absence penalty or excused-absence procedure in
it — rather than inventing one.
