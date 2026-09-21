# HW 4 evaluation

The app is in [`HW4.py`](HW4.py). Raw output from every run is in
[`HW4_transcripts.md`](HW4_transcripts.md).

## Setup

The corpus is all 513 'Cuse Activities organization pages, in
[`HW4-Data/`](HW4-Data). Each page is parsed with BeautifulSoup, split into
exactly two mini-documents, and embedded with OpenAI `text-embedding-3-small`
into a persistent ChromaDB collection. A question retrieves the five closest
organizations, and the whole page for each one goes into the prompt.

I ran the five questions as one continuous conversation on both
`gpt-5-mini` — the sidebar default — and `gpt-5.5`, then re-ran the last
question alone as a control. Every answer came out of the real page driven
through `streamlit.testing.v1.AppTest`, so each run used the same retrieval,
system prompt, and 10-message buffer a person using the app gets.

### The vector database is built once

| | |
| --- | --- |
| First run, empty directory | 10.3s and 16.2s on two separate cold builds; 1,026 mini-documents written to `HW4-ChromaDB/` (22 MB) |
| Every run after, new process | 0.14s to open the collection, `count() == 1026`, zero embedding calls |

I tested this properly rather than assuming it: I deleted `HW4-ChromaDB/`,
ran the page, and watched it rebuild from `HW4-Data/` alone and then answer a
question correctly. Opening an existing collection is effectively instant; the
few seconds a warm start still takes are Python importing chromadb and
streamlit, not the database.

`get_collection()` opens a `PersistentClient` and only embeds when
`collection.count() == 0`, so the database survives the process exiting.
Deleting `HW4-ChromaDB/` is the only thing that forces a rebuild.

### Chunking

Two mini-documents per page, cut at the midpoint and snapped forward to the
next space. The full reasoning is in the `split_in_two()` docstring; the short
version is that the assignment asks for a countable two per document, these
pages are short and uniform enough that halves land near 800 characters, and
the halves tend to fall along the page's own structure — what the organization
is, then when it meets and who runs it.

## The five questions, and why

I picked questions that probe different parts of the configuration rather than
five that the same mechanism would answer.

**1. When and where does the Society of Women Engineers meet, and who is their
president?**

A named organization, asking for facts that live in the *second* half of its
page. This is the question that tests whether halving a document breaks it.
SWE is the sharpest possible case: its meeting time is severed exactly at the
seam. Half 0 ends with `Meeting time:` and half 1 begins with
`5:00 AM/PM: PM`. Neither half alone answers the question.

**2. Which student organizations focus on sustainability or the environment?**

Thematic rather than named. Nothing in the question matches an organization's
title, so this measures whether the embeddings actually capture what a club is
about, and it is the question where `TOP_K = 5` becomes a ceiling.

**3. What does the Data Science Club do, and when do they meet?**

A hallucination trap. The Data Science Club page exists and ranks first easily,
but almost every field on it reads `No Response` — no description, no meeting
day, no officers. The right answer is to say the directory does not say. A
model inclined to fill gaps has an obvious, plausible answer available here,
because it knows what a data science club does.

**4. Is there a chess club at Syracuse I could join?**

Absent from the corpus — I confirmed there is no chess club among the 513
organizations. Retrieval will still return five pages, because it always does,
so this tests whether the bot notices that none of them answer the question
instead of treating the closest match as the answer.

**5. Going back to the engineering group I asked about first — who is its
faculty advisor?**

A follow-up that is meaningless without the conversation. It names no
organization, so the referent can only come from memory. I also ran it alone in
a fresh conversation as a control, so the buffer's contribution could be
isolated rather than assumed.

## Results

| Question | `gpt-5-mini` | `gpt-5.5` |
| --- | :--: | :--: |
| 1. SWE meeting and president | correct | correct |
| 2. Sustainability organizations | partial | partial |
| 3. Data Science Club | correct | correct |
| 4. Chess club | correct | correct |
| 5. Follow-up advisor | referent right, answer missing | referent right, answer missing |

"Partial" on Q2 means the answer was accurate about the organizations it
returned but did not find all the relevant ones.

Total latency for the five-turn conversation was 46.3s on `gpt-5-mini` and
23.2s on `gpt-5.5`. The premium model was consistently the faster of the two
here, which I did not expect.

### Q1 — the chunk seam held

Both models answered "Wednesday at 5:00 PM", with President Luiza Ouwor, and
both reported the meeting location as `No Response` rather than inventing one.
SWE came back first at distance 0.619, a clear gap to second place at 0.878.

This is the single result I would point to in defence of the design. The fact
asked for is split across the two mini-documents, and the answer was still
correct, because retrieval matches half-pages but `fetch_page()` reassembles
the whole page before it goes to the model. It is also the empirical reason the
chunker uses no overlap: overlap exists to stop exactly this kind of severing,
and reassembly already prevents it.

### Q3 and Q4 — the bot does not fill in gaps

On Q3 both models said plainly that the description and all meeting fields are
`No Response`, gave the one real fact on the page (the contact email
`mgarciam@syr.edu`), and left it there. Neither described what a data science
club does. On Q4 both opened with "Not in the organization pages" and offered
the Gaming Club as the nearest real alternative, correctly attributing its
Friday 7:00 PM Hinds Hall meeting to the directory. The two-part disclosure
rule in the system prompt is doing real work: the bot distinguishes what it
read from what it knows.

### Q2 — retrieval is the ceiling, not the model

Both models were accurate about what they were given, and both flagged that the
Geology and Biology graduate organizations have `No Response` descriptions and
so cannot be confirmed as environmental. That is the right instinct.

But the five retrieved pages are not the five best answers. Food Recovery
Network, whose page describes a "dual mission of feeding people and reducing
food waste" and recovering "over 7 tons of food", never entered the top five —
while two organizations with no description at all did, presumably matching on
boilerplate alone. The directory has more environment-adjacent organizations
than five, so a thematic question like this one is capped by `TOP_K` before the
model ever sees it.

### Q5 — memory works, retrieval does not know about it

This produced the most useful result in the evaluation, and it is a clean
three-way split.

*Memory succeeded.* Both models resolved "the engineering group I asked about
first" to the Society of Women Engineers. The referent was four turns back and
still inside the 10-message buffer.

*Retrieval failed.* The five pages retrieved were ASCE, Peer Advisors,
ASME, Graduate Science Policy Group and Engineering World Health. SWE was not
among them. `search()` embeds only the current prompt, and the bare text
"the engineering group I asked about first" carries no signal about SWE.

*The bot handled the mismatch honestly.* Both models said they could not verify
the advisor from the pages they had rather than answering from a page that
happened to be in front of them. `gpt-5.5` went one step further and offered
ASCE's advisor, Yilei Shi, clearly labelled as a different organization.

The control confirms the diagnosis. Asked the same question with no prior
conversation, `gpt-5.5` had no referent to resolve, took ASCE off the top of
the retrieval, and answered confidently about it — as though that were the
organization I meant. The buffer is what supplied the referent; nothing else
could have.

What makes this a genuine defect rather than a coverage gap is that the answer
is in the corpus. SWE's page lists **Dr. Sinead MacNamara** as its full-time
faculty advisor. The bot had the right organization in mind and the right fact
on disk, and the two never met.

## Would I change anything?

Yes — one thing, and I measured it before recommending it.

**Make retrieval conversation-aware.** The query sent to the embedding model
should include recent conversation, not just the latest prompt. I tested the
cheapest version of this — prepending the previous user turn to the follow-up
before embedding, changing nothing else:

| Query embedded | Where SWE ranks |
| --- | --- |
| The follow-up alone (what the app does now) | not in the top five |
| Previous user turn + the follow-up | **first, at distance 0.593** |

0.593 is closer than the 0.619 SWE scored on Q1's direct, fully-specified
question, so on this question the fix does not merely repair retrieval, it
improves it. With SWE's page in the prompt, Q5 becomes answerable from the
directory.

I left this out of the submitted app deliberately. The five transcripts
describe the configuration as it stands, and swapping in an untested change
would invalidate the Q1–Q4 results it was never evaluated against. A proper
version would also need care: a naive concatenation would drag stale context
into unrelated new questions, so the real implementation is a small
query-rewriting step that condenses the history and the new question into one
search string, and that deserves its own evaluation rather than a late edit.

Two smaller changes I would consider, neither urgent:

- **Raise `TOP_K` for thematic questions.** Q2 is capped by retrieval breadth,
  not by the model. These pages are short — the median is about 1,600
  characters — so ten pages would still be a modest prompt. Q1, Q3 and Q4 do
  not need it, so this is a trade of cost against recall on one question type
  out of four.
- **Nothing about the chunking.** Two mini-documents per page is the
  assignment's requirement, and Q1 shows the seam is not costing accuracy.
  If I were free of the constraint I would still split these pages rather than
  embed them whole, because purpose and logistics are genuinely different
  topics and a single vector blurs them.

## Model choice

`gpt-5-mini`, the sidebar default, is the right default. It matched `gpt-5.5`
on all five questions and was not meaningfully worse anywhere. It is more
verbose — it padded Q3 and Q4 with next-step suggestions — while `gpt-5.5` was
tighter and, in this run, about twice as fast overall.

Two small prompt-compliance slips are worth recording, both on `gpt-5-mini` and
neither an error of fact. On Q4 it used both disclosure lines in one answer,
opening with "Not in the organization pages" and then heading its Gaming Club
paragraph "From the organization pages". On Q5 it opened with "Not in the
organization pages — answering from general knowledge" and then did not answer
from general knowledge; it said it did not know, which was the better response
but not what the line announced.

## Caveats

I asked the five questions in sequence in one conversation, which is what
exercises the memory and is the point of Q5, but it does mean later questions
could see earlier turns. The control run isolates that effect for Q5, the only
question where it matters. I ran each conversation once; these models are not
deterministic, so wording would shift on a re-run, though the retrieval results
are deterministic and the coverage findings are structural.

## Implementation notes

`requirements.txt` needed no change. HW4 imports `streamlit`, `chromadb`,
`bs4`, and `openai`, all already listed, with `bs4` coming from
`beautifulsoup4`. The `pysqlite3-binary` pin for Linux and the shim at the top
of `HW4.py` are both carried over from Lab 4 and are what let ChromaDB run on
Streamlit Community Cloud.

`HW4-ChromaDB/` is gitignored. It is generated from `HW4-Data/`, so the first
run on a fresh deployment rebuilds it once, in the ten to sixteen seconds
measured above, and every run after that opens it. Streamlit Community Cloud
has a slower CPU than this machine and sleeps idle apps, so expect the first
load there to take longer than either figure.
