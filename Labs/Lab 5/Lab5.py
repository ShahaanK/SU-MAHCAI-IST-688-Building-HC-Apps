import json
from urllib.parse import quote

import requests
import streamlit as st
from openai import OpenAI

# Used when the model asks for weather without naming a location.
DEFAULT_LOCATION = "Syracuse, NY"

CHAT_MODELS = {
    "gpt-5-mini (fast)": "gpt-5-mini",
    "gpt-5.4-mini (fast, newer)": "gpt-5.4-mini",
    "gpt-5.5 (premium)": "gpt-5.5",
}

# wttr.in reports the day in three-hour slots of local time ("0", "300", ...
# "2100"). Only the waking hours are kept: the advice is for today's outfit,
# and 3 AM conditions would only crowd the prompt.
DAYTIME_HOURS = range(6, 24, 3)

# Sent with the first call. The model only decides whether it needs the
# weather; the advice itself is asked for in the second call.
TOOL_PROMPT = """You help people decide what to wear and what to do outdoors \
today. You have a get_current_weather tool. Call it before answering any \
request that depends on the weather, which is almost every request here. If \
the user names no location, call it with no arguments; it defaults to \
Syracuse, NY. If the input is clearly not a place or a weather question, do \
not call the tool; reply in one sentence asking for a city instead."""

# Sent with the second call, alongside the weather the tool returned.
ADVICE_PROMPT = """You are a practical "What to Wear" assistant. The \
get_current_weather tool result above is today's weather, in Fahrenheit, mph \
and inches. Base your advice only on that data.

Write three short sections with these headings:

**Weather today** - one or two sentences on what it is like now and how it \
changes through the day (warming up, rain arriving in the afternoon, cooling \
after sunset).

**What to wear** - a bulleted list of specific clothing. Go by the feels-like \
temperature. Suggest layers if the day swings by 15 degrees or more, and add \
rain gear, sun protection or cold-weather items when the data calls for them.

**Outdoor activities** - three or four activities that suit today's \
conditions, each with the best time of day for it. If it is a poor day to be \
outside (thunderstorms, heavy rain, extreme heat or cold), say so and suggest \
the best window or lower-exposure options.

matched_location is the weather area wttr.in picked, which is often a \
neighborhood or suburb of the requested city (e.g. Galeville for Syracuse); \
that is expected, so do not mention it. Only if it is in a different state, \
region or country from what the user asked for, say so in one line before the \
first section. Keep the whole answer under 250 words."""

# The tool definition handed to the OpenAI API. location is optional so the
# model can call the tool when the user gives no city; the default is applied
# in run_weather_tool().
WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_current_weather",
        "description": (
            "Get the current weather and today's forecast for a location: "
            "conditions now, the high and low, sunrise and sunset, and "
            "conditions every three hours from 6 AM to 9 PM local time. If "
            "the user gives no location, call it with no arguments and "
            f"{DEFAULT_LOCATION} is used."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": (
                        "A city, e.g. 'Syracuse, NY' or 'Lima, Peru'. A zip "
                        "code, an airport code ('SYR') or a landmark also "
                        "works. Keep the state or country if the user gave one."
                    ),
                },
            },
            "required": [],
        },
    },
}

st.title('Lab 5 — The "What to Wear" Bot')
st.write(
    "Enter a city and get advice on what to wear today and which outdoor "
    "activities suit the weather. The LLM is given a weather tool and decides "
    "for itself when to call it; the live forecast comes from wttr.in. Leave "
    f"the box empty to use {DEFAULT_LOCATION}."
)


class WeatherError(Exception):
    """wttr.in could not return weather for the requested location."""


def get_openai_client():
    """One OpenAI client per session, reused for both calls."""
    if "openai_client" not in st.session_state:
        try:
            api_key = st.secrets["OPENAI_API_KEY"]
        except (KeyError, FileNotFoundError):
            st.error(
                "No `OPENAI_API_KEY` found. Add it to `.streamlit/secrets.toml` "
                "locally, or to **Settings > Secrets** on Streamlit Community "
                "Cloud.",
                icon="🗝️",
            )
            st.stop()
        st.session_state.openai_client = OpenAI(api_key=api_key)
    return st.session_state.openai_client


def value(field):
    """wttr.in wraps text fields as [{"value": ...}]; unwrap one."""
    return field[0]["value"].strip() if field else ""


def hour_label(slot_time):
    """Turn a wttr.in slot time such as "1500" into "3 PM"."""
    hour = int(slot_time) // 100
    return f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"


# location can be a city, a zip code, an airport code ('SYR'),
# or a landmark ('Eiffel+Tower')
# note: hard codes units to degrees Fahrenheit
# Cached for 10 minutes: the forecast barely changes in that time, and it
# spares wttr.in repeat requests for the same city.
@st.cache_data(ttl=600, show_spinner=False)
def get_current_weather(location):
    # Commas and plus signs stay literal because wttr.in reads them: an
    # escaped comma sends "Syracuse, NY" to a different town. Everything else
    # is escaped so a "/", "?" or "#" in the input cannot rewrite the URL.
    url = f"https://wttr.in/{quote(location, safe='+,')}?format=j1"
    response = requests.get(url, timeout=10)
    # An unknown location comes back as a 500 with a plain-text "location not
    # found" body, not as JSON.
    if response.status_code != 200:
        if "not found" in response.text.lower():
            raise WeatherError(f"Could not find a location named {location}")
        raise WeatherError(f"wttr.in error: status {response.status_code}")
    try:
        data = response.json()
    except ValueError:
        raise WeatherError(f"Could not find a location named {location}")

    # j1 has three top-level sections:
    #   current_condition -- one entry, conditions right now
    #   weather           -- three entries, one per day, each with
    #                        min/max, astronomy, and hourly forecasts
    #   nearest_area      -- the location wttr.in actually matched
    current = data["current_condition"][0]
    today = data["weather"][0]
    astronomy = today["astronomy"][0]
    area = data["nearest_area"][0]

    # Hourly slots are what shows the day changing: a cold morning, an
    # afternoon shower, wind picking up after sunset.
    hourly = [
        {
            "time": hour_label(slot["time"]),
            "description": value(slot["weatherDesc"]),
            "temperature_F": float(slot["tempF"]),
            "feels_like_F": float(slot["FeelsLikeF"]),
            "chance_of_rain_pct": int(slot["chanceofrain"]),
            "chance_of_snow_pct": int(slot["chanceofsnow"]),
            "chance_of_thunder_pct": int(slot["chanceofthunder"]),
            "precip_in": float(slot["precipInches"]),
            "wind_mph": int(slot["windspeedMiles"]),
            "wind_gust_mph": int(slot["WindGustMiles"]),
            "uv_index": int(slot["uvIndex"]),
        }
        for slot in today["hourly"]
        if int(slot["time"]) // 100 in DAYTIME_HOURS
    ]

    matched = [value(area.get(key)) for key in ("areaName", "region", "country")]
    return {
        "location": location,
        # Shown to the user and the model, because wttr.in matches loosely.
        # Usually it just names a nearby area ("Syracuse, NY" comes back as
        # Galeville, a neighborhood a few miles north), but the zip code
        # "10001" alone resolves to Cáceres, Spain.
        "matched_location": ", ".join(part for part in matched if part),
        "date": today["date"],
        "now": {
            "description": value(current["weatherDesc"]),
            "temperature_F": float(current["temp_F"]),
            "feels_like_F": float(current["FeelsLikeF"]),
            "humidity_pct": int(current["humidity"]),
            "wind_mph": int(current["windspeedMiles"]),
            "wind_direction": current["winddir16Point"],
            "precip_in": float(current["precipInches"]),
            "cloud_cover_pct": int(current["cloudcover"]),
            "uv_index": int(current["uvIndex"]),
            "visibility_miles": float(current["visibilityMiles"]),
        },
        "today": {
            "high_F": float(today["maxtempF"]),
            "low_F": float(today["mintempF"]),
            "max_chance_of_rain_pct": max(h["chance_of_rain_pct"] for h in hourly),
            "max_chance_of_snow_pct": max(h["chance_of_snow_pct"] for h in hourly),
            "snowfall_in": round(float(today["totalSnow_cm"]) / 2.54, 1),
            "max_uv_index": int(today["uvIndex"]),
            "sunrise": astronomy["sunrise"],
            "sunset": astronomy["sunset"],
        },
        "through_the_day": hourly,
    }


def run_weather_tool(tool_call):
    """Execute one get_current_weather call the model asked for."""
    try:
        args = json.loads(tool_call.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    # The model may omit location, or send an empty string, when the user
    # named no place.
    location = (args.get("location") or "").strip() or DEFAULT_LOCATION
    return location, get_current_weather(location)


def show_weather(weather):
    """A compact summary of the forecast the advice is based on."""
    now, today = weather["now"], weather["today"]
    # Headed with the place the user asked for; wttr.in's own name for the
    # area is often a neighborhood of it, so it goes underneath.
    st.subheader(f"Weather for {weather['location']}")
    st.caption(
        f"Nearest wttr.in weather area: {weather['matched_location']} · "
        f"forecast for {weather['date']}"
    )
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Now", f"{now['temperature_F']:.0f}°F", now["description"],
                delta_color="off", delta_arrow="off")
    col2.metric("Feels like", f"{now['feels_like_F']:.0f}°F")
    col3.metric("High / Low", f"{today['high_F']:.0f}° / {today['low_F']:.0f}°")
    col4.metric("Chance of rain", f"{today['max_chance_of_rain_pct']}%")


def text_chunks(stream):
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


with st.sidebar:
    st.header("Model")
    choice = st.selectbox("Which LLM?", list(CHAT_MODELS))
    model = CHAT_MODELS[choice]
    st.caption(f"Chat: `{model}`")
    st.caption("Weather: [wttr.in](https://wttr.in), no API key needed")

with st.form("city_form"):
    city = st.text_input("City", placeholder="e.g. Syracuse, NY or Lima, Peru")
    submitted = st.form_submit_button("Get advice")

if submitted:
    city = city.strip()
    request = f"What should I wear today in {city}?" if city else "What should I wear today?"
    messages = [
        {"role": "system", "content": TOOL_PROMPT},
        {"role": "user", "content": request},
    ]
    client = get_openai_client()

    # First call: tool_choice="auto" lets the model decide whether it needs
    # the weather at all.
    with st.spinner("Thinking..."):
        first = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=[WEATHER_TOOL],
            tool_choice="auto",
        )
    reply = first.choices[0].message

    if not reply.tool_calls:
        # The model answered without the weather (e.g. the input wasn't a
        # place), so there is nothing to base clothing advice on.
        st.markdown(reply.content)
        st.stop()

    # Every tool call the model makes needs its own "tool" reply, matched by
    # id, or the second call is rejected.
    tool_messages, lookups = [], []
    for tool_call in reply.tool_calls:
        try:
            with st.spinner("Getting the weather..."):
                location, weather = run_weather_tool(tool_call)
        except (WeatherError, requests.RequestException) as error:
            st.error(
                f"{error}. Try adding the state or country, e.g. "
                "“Portland, OR” or “Lima, Peru”.",
                icon="🌦️",
            )
            st.stop()
        tool_messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(weather),
        })
        lookups.append((tool_call, location, weather))

    if not city:
        st.info(f"No city entered, so the forecast is for {DEFAULT_LOCATION}.")
    for _, _, weather in lookups:
        show_weather(weather)

    # Second call: the weather goes back to the model as the tool result, and
    # ADVICE_PROMPT asks for today's clothing and outdoor activities.
    # The assistant turn is rebuilt by hand rather than dumped from the SDK
    # object, which carries response-only fields the request does not take.
    advice_messages = [
        {"role": "system", "content": ADVICE_PROMPT},
        {"role": "user", "content": request},
        {
            "role": "assistant",
            "content": reply.content,
            "tool_calls": [tool_call.model_dump() for tool_call in reply.tool_calls],
        },
        *tool_messages,
    ]
    stream = client.chat.completions.create(
        model=model,
        messages=advice_messages,
        stream=True,
    )
    st.subheader("What to wear and do today")
    st.write_stream(text_chunks(stream))

    with st.expander("Tool call and weather data sent to the model"):
        for tool_call, location, weather in lookups:
            st.markdown(
                f"`{tool_call.function.name}({tool_call.function.arguments})` "
                f"→ looked up **{location}**"
            )
            st.json(weather)
