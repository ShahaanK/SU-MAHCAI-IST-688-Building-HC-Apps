---
name: new-lab
description: Build a new Lab or HW page in this repo's Streamlit apps. Use when starting a lab or homework assignment from its handout.
---

1. **Map the handout.** List every numbered requirement. Done when each one names the function or call that will satisfy it.
2. **Build on the right branch.** Use `Labs` for labs and `HW` for homework (deploy details live in `ship-hw`).
3. **Create and register the page.**
   - Lab: create `Labs/Lab N/LabN.py`, then register it in `Labs/streamlit_app.py`.
   - HW: create `HW/HWN.py`, then register it in `HW_Manager.py`.
   - The newest page takes `default=True`, and the previous default becomes `False`; two defaults is an error.
   - Add a bullet to `Labs/home.py` (labs only), and update both README tables: the pages row and the `OPENAI_API_KEY` row.
   - Add any new import to `requirements.txt`, since Streamlit Cloud installs from it.
4. **Copy patterns from the newest page of the same kind.** Use `get_openai_client()` with its secrets error, the `CHAT_MODELS` sidebar picker and `text_chunks()` for streaming. ChromaDB pages also need the `pysqlite3` swap from `Lab4.py`.
5. **Verify** with `test-streamlit-page`, then ship with `ship-hw`.

Conventions the code won't tell you:
- Pages share one session, so prefix `st.session_state` keys with the page (`lab4_messages`, `Lab4_VectorDB`).
- Resolve data paths from `__file__`, because the working directory is the repo root.
- "Not a chatbot" in a handout means `st.form` with a submit button and no history.
- For the gpt-5 family, pass only `model`, `messages`, `tools`, `tool_choice` and `stream`; `temperature` and `max_tokens` are rejected.

OpenAI tool calling (Lab 5, HW 5):
- The first call passes `tools=[...]` and `tool_choice="auto"`. `reply.tool_calls` can be `None`, so show `reply.content` instead.
- Optional arguments arrive missing or as `""`, so apply defaults in code (`args.get("x") or DEFAULT`) as well as in the schema description.
- For the second call, rebuild the assistant turn by hand as `{"role": "assistant", "content": ..., "tool_calls": [tc.model_dump() ...]}`. `reply.model_dump()` carries response-only fields such as `annotations`.
- Every `tool_call_id` needs its own `{"role": "tool", ...}` reply, or the second call returns a 400.
- Put the task instruction (what the answer must contain) in the second call's own messages, beside the tool result.
