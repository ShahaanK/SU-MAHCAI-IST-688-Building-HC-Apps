# SU-MAHCAI-IST-688
Covering course IST 688

This repo holds two separate Streamlit apps, each with its own entry point.

| App | Run from repo root | Pages |
| --- | --- | --- |
| Labs | `streamlit run Labs/streamlit_app.py` | Home, Lab 1, Lab 2 |
| HW Manager | `streamlit run HW_Manager.py` | HW 1, HW 2 |

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## API keys

Copy the example file and fill in your own keys:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

| Key | Needed for | Get one at |
| --- | --- | --- |
| `OPENAI_API_KEY` | Lab 2, and the OpenAI option in HW 2 | https://platform.openai.com/api-keys |
| `OPENROUTER_API_KEY` | the OpenRouter options in HW 2 | https://openrouter.ai/keys |

`secrets.toml` is gitignored and must never be committed.

Streamlit resolves `.streamlit/secrets.toml` relative to the directory you launch
from, so run both apps from the repo root or the keys will not be found. Lab 1 also
accepts a key typed into the page, so it works without a secrets file.

On Streamlit Community Cloud there is no secrets file — paste the same contents into
the app's **Settings > Secrets** instead.
