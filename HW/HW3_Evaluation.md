# HW 3 evaluation

The app is in [`HW3.py`](HW3.py). Raw output from every run is in [`HW3_transcripts.md`](HW3_transcripts.md).

## Setup

I used each vendor's premium model: OpenAI's `gpt-5.5` called directly, and Anthropic's `claude-opus-5` through OpenRouter. I checked both IDs against the live model lists before running anything. The sidebar also offers `gpt-5.4-mini` and `claude-haiku-4.5` for cheap testing, but I did not use those here.

The two pages:

* How Baseball Works, "The Basics" (6,022 characters)
* PBS / Ken Burns, "Baseball for Beginners" (12,863 characters)

Every answer below came out of the real HW3 page, driven through `streamlit.testing.v1.AppTest` rather than by calling the APIs separately. So each run used the same scraping, system prompt, and 6-message buffer that a person using the app gets.

## The three questions, and why

I picked questions the two pages do not both answer. If either page covered everything, all four scenarios would score the same and the comparison would show nothing.

**1. How far apart are the bases, and how far is the pitcher's mound from home plate?**

Only How Baseball Works gives numbers: 90 feet between bases, 60.5 feet to the mound. PBS describes the diamond without a single measurement. I wanted to know whether adding a second, longer page would dilute an answer the model already had, which seemed like a real risk once you double the context.

**2. What is ERA, and how exactly is it calculated?**

The reverse. Only PBS defines Earned Run Average and gives the arithmetic in prose. The Basics page never mentions ERA. This one also tests honesty, since with only the first page the right move is to say so instead of reciting ERA from memory.

**3. When a batter is walked, what happens? Name all nine defensive positions, and say whether a game can end in a tie.**

Three parts on purpose. Both pages explain walks. Only PBS lists the nine positions, in its glossary entry for "Fielder". Only How Baseball Works covers ties and extra innings. No single page answers all three, so this measures whether the bot can pull from two sources in one answer.

I also added a fourth turn to every run asking what my first question had been. That is a memory probe rather than a content question, and I come back to it below.

## Scenarios

| URLs given | `gpt-5.5` | `claude-opus-5` |
| --- | --- | --- |
| One URL (How Baseball Works) | S1 | S2 |
| Both URLs | S3 | S4 |
| One URL (PBS), extra | S5 | S6 |

S1 through S4 are the four the assignment asks for. I used How Baseball Works as the single page for the one-URL runs. S5 and S6 are extra, so the "did both pages help" question can be answered in both directions instead of only showing that adding PBS helped.

## Results

"Partial" below always means the model said the page did not cover it.

| Question | S1 GPT, 1 doc | S2 Opus, 1 doc | S3 GPT, both | S4 Opus, both |
| --- | :--: | :--: | :--: | :--: |
| Distances | yes | yes | yes | yes |
| ERA formula | partial | partial | yes | yes |
| Walk | yes | yes | yes | yes |
| Nine positions | partial | partial | yes | yes |
| No ties | yes | yes | yes | yes |
| **Answered** | **3/5** | **3/5** | **5/5** | **5/5** |

The PBS-only runs (S5, S6) also scored 3/5, failing the opposite two: no distances, no explanation of ties.

I checked every direct quotation against the scraped text and all of them were accurate. That includes a strike zone definition Opus quoted ("from the bottom of the batter's kneecaps to the midpoint between the top of the batter's shoulders") that I assumed was invented until I found it verbatim in the PBS glossary. I spot-checked the claims that were not quotations and found nothing fabricated, though I did not verify all of them.

## Did having both documents improve the answers?

Yes, and the reason is that the two pages cover different ground rather than the same ground twice. Coverage went from 3/5 to 5/5 for both models.

Question 3 shows it most clearly. Given only How Baseball Works, both models said outright that they could not name the nine positions. GPT-5.5 wrote that the page "specifically mentions the pitcher and catcher, but it does not list all nine defensive positions." Given both pages, each model produced the full list from the PBS glossary and the no-ties rule from How Baseball Works in a single answer. That is two facts from two sources combined, not two summaries stapled together.

The PBS-only runs confirm this works both ways. With PBS alone the models could list the positions but could no longer give any field dimensions or explain extra innings, which are exactly the facts the other page supplies. Each page fills a hole in the other.

Adding the second page also cost nothing, which is what question 1 was there to check. The extra text more than doubled the context, so a vaguer or more hedged answer was plausible. It did not happen. The distances came back just as confidently in S3 and S4 as in S1 and S2. Attribution actually got better: with one page the models say "the page", while with two they name which page each fact came from, so the answers are easier to check.

Precision improved too. Given both pages, Opus quoted the PBS strike zone wording instead of the vaguer version in How Baseball Works ("above the hitter's knees, below the mid point of his waist and shoulders"). With two sources it could pick the better-worded one.

The gain depends on the pages complementing each other. Two pages covering the same material would add cost and latency for nothing, and since every document is re-sent on every turn, this does not scale far.

## Which model was best?

Claude Opus 5 gave the better answers. GPT-5.5 was much cheaper and faster. For this assignment I would pick Opus, though the gap is smaller than the difference in length suggests.

On correctness they tied. Both scored 3/5 with one page and 5/5 with two, and neither made anything up. What separated them was how they behaved around the answer.

Opus handled gaps more usefully. Asked about ERA with only the first page, GPT-5.5 said it was not covered and stopped there. Opus said the same, then noticed that the scraped navigation menu listed a separate "Statistics" page, told me that was where the answer lived, and offered to explain if I gave it that page. It turned a dead end into a next step, using information that was genuinely in the scrape. On the three-part question it also marked each sub-answer as covered or not, so I could see at a glance which parts the sources supported. It volunteered related facts as well, like the outfield wall distance of 325 to 450 feet and the 17 inch home plate, and it flagged that PBS only defines "error" indirectly.

GPT-5.5 won on everything operational. A four-turn conversation with both pages took 9.1 seconds against 27.9 for Opus, and Opus produced about 2.3 times as much text, which costs more on top of it being the pricier model per token. GPT answered the distances question in two lines. Opus's extra context is useful when you want it and noise when you don't.

So for a homework chatbot explaining a document to someone new to the subject, Opus's thoroughness and its handling of gaps are worth the wait, and most of its extra length is doing real work. For anything with traffic I would default to GPT-5.5, which got every factual answer right at a fraction of the latency and cost. The two models were about equally accurate and differed mainly in manner.

## What the buffer did

The fourth turn gave the most useful result in the whole evaluation. When I asked "what was the very first thing I asked you?", every single run answered "what is ERA", which was my second question.

That is the buffer working, not the model forgetting. After four turns the history holds seven messages. The code keeps the last six, which starts on an assistant reply whose question has already been cut, so that orphan is dropped too and the window begins with my ERA question. The first question has aged out. Both models accurately reported the oldest thing still in front of them.

The system prompt carrying both documents was still fully present during that same turn, which is why the answers could still quote the sources. Documents stay, conversation scrolls. The transcript on screen still shows all four turns, and only what gets sent to the model is trimmed.

## Caveats

I asked the three questions in sequence in one conversation, so question 3 could see the earlier exchange. That is deliberate, since it is what exercises the memory, and it applies equally to all six runs, so the model comparison is still fair. I ran each scenario once. These models are not deterministic, so exact wording and length would shift on a re-run, but the coverage results are structural and would not.

## Implementation notes

Memory is a rolling buffer of the last 6 messages, so 3 exchanges, set by `BUFFER_MESSAGES` in `HW3.py`. The URL text sits in a system prompt that is rebuilt and re-sent every turn, so the documents are never dropped.

`requirements.txt` needed no change. HW3 imports only `streamlit`, `requests`, `bs4`, and `openai`, and all four are already listed, with `bs4` coming from `beautifulsoup4`. I checked by parsing the imports out of the file rather than reading through it.
