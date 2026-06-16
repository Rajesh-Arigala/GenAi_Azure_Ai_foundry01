import os
import json
import time
import requests
from pathlib import Path
from azure.identity import DefaultAzureCredential
from azure.ai.agents import AgentsClient

# ── module-level API key (set during TravelAgent.setup) ──────
_OWM_API_KEY = ""

TOOL_STATUS_MSG = {
    "file_search":      "📄 Searching destination files...",
    "code_interpreter": "🐍 Running Python code...",
    "bing_grounding":   "🌐 Browsing the web...",
    "function":         "⚙️ Calling live APIs...",
}
TOOL_LABELS = {
    "file_search":      "File Search",
    "code_interpreter": "Code Interpreter",
    "bing_grounding":   "Bing Search",
    "function":         "Function Call",
}
TOOL_COLORS = {
    "file_search":      "#10b981",
    "code_interpreter": "#8b5cf6",
    "bing_grounding":   "#3b82f6",
    "function":         "#f59e0b",
}


# ── Module-level tool functions ───────────────────────────────
# Must be at module level (not methods) for FunctionTool to work

def fetch_weather(location: str) -> str:
    """Get current weather for a city — returns temperature, condition, humidity, and wind speed."""
    try:
        r = requests.get(
            "http://api.openweathermap.org/data/2.5/weather",
            params={"q": location, "appid": _OWM_API_KEY, "units": "metric"},
            timeout=10,
        )
        r.raise_for_status()
        d = r.json()
        return json.dumps({
            "location":      location,
            "temperature_c": d["main"]["temp"],
            "feels_like_c":  d["main"]["feels_like"],
            "condition":     d["weather"][0]["description"].capitalize(),
            "humidity_pct":  d["main"]["humidity"],
            "wind_kmh":      round(d["wind"]["speed"] * 3.6, 1),
        })
    except Exception as e:
        return json.dumps({"error": str(e), "location": location})


def get_exchange_rate(from_currency: str, to_currency: str, amount: float = 1.0) -> str:
    """Get live exchange rate between two currencies and convert an optional amount."""
    try:
        r = requests.get(
            f"https://api.exchangerate-api.com/v4/latest/{from_currency.upper()}",
            timeout=10,
        )
        r.raise_for_status()
        rate = r.json()["rates"].get(to_currency.upper())
        if not rate:
            return json.dumps({"error": f"Currency '{to_currency}' not found"})
        return json.dumps({
            "from":      from_currency.upper(),
            "to":        to_currency.upper(),
            "rate":      rate,
            "amount":    amount,
            "converted": round(amount * rate, 2),
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── TravelAgent ───────────────────────────────────────────────

class TravelAgent:
    def __init__(self):
        self.ready         = False
        self.error         = None
        self.agents_client = None
        self.agent         = None
        self.thread        = None

    # ── public API ───────────────────────────────────────────

    def setup(self):
        global _OWM_API_KEY
        try:
            config       = self._load_config()
            _OWM_API_KEY = config.get("OPENWEATHER_API_KEY",
                                      os.environ.get("OPENWEATHER_API_KEY", ""))
            endpoint     = config["PROJECT_ENDPOINT"]
            agent_id     = config.get("AGENT_ID", "").strip()

            if not agent_id:
                raise ValueError(
                    'AGENT_ID not found in cred.json. '
                    'Add "AGENT_ID": "asst_xxxx" to your cred.json.'
                )

            cred = DefaultAzureCredential()
            self.agents_client = AgentsClient(endpoint=endpoint, credential=cred)

            # Just fetch the existing agent — no uploads, no creation
            self.agent  = self.agents_client.get_agent(agent_id)
            self.thread = self.agents_client.threads.create()
            self.ready  = True
            print(f"  ✅ Connected to agent: {self.agent.id} ({self.agent.name})")
        except Exception as exc:
            self.error = str(exc)
            raise

    def reset_thread(self):
        self.thread = self.agents_client.threads.create()

    def ask_stream(self, question: str):
        """Generator — yields SSE-ready event dicts."""

        self.agents_client.messages.create(
            thread_id=self.thread.id, role="user", content=question
        )
        run = self.agents_client.runs.create(
            thread_id=self.thread.id, agent_id=self.agent.id
        )
        yield {"type": "status", "message": "🤔 Agent is thinking..."}

        seen_step_ids: set = set()

        while run.status in ("queued", "in_progress", "requires_action"):
            time.sleep(1)
            run = self.agents_client.runs.get(
                thread_id=self.thread.id, run_id=run.id
            )

            # ── show which tool is running ────────────────────
            try:
                steps = self.agents_client.run_steps.list(
                    thread_id=self.thread.id, run_id=run.id
                )
                for step in steps:
                    if step.id not in seen_step_ids and step.type == "tool_calls":
                        seen_step_ids.add(step.id)
                        for tc in step.step_details.tool_calls:
                            t = getattr(tc, "type", "")
                            if t in TOOL_STATUS_MSG:
                                yield {"type": "status", "message": TOOL_STATUS_MSG[t]}
            except Exception:
                pass

            # ── handle function calls ─────────────────────────
            if run.status == "requires_action":
                yield {"type": "status", "message": TOOL_STATUS_MSG["function"]}
                outputs = []
                for tc in run.required_action.submit_tool_outputs.tool_calls:
                    fn   = tc.function.name
                    args = json.loads(tc.function.arguments)
                    if fn == "fetch_weather":
                        result = fetch_weather(args.get("location", ""))
                    elif fn == "get_exchange_rate":
                        result = get_exchange_rate(
                            args.get("from_currency", "USD"),
                            args.get("to_currency",   "INR"),
                            args.get("amount",        1.0),
                        )
                    else:
                        result = json.dumps({"error": f"Unknown function: {fn}"})
                    outputs.append({"tool_call_id": tc.id, "output": result})

                self.agents_client.runs.submit_tool_outputs(
                    thread_id=self.thread.id, run_id=run.id, tool_outputs=outputs
                )

        if run.status != "completed":
            yield {"type": "error", "message": f"Run ended with status: {run.status}"}
            return

        # ── collect tools used (for badge display) ────────────
        tools_used = []
        try:
            steps = self.agents_client.run_steps.list(
                thread_id=self.thread.id, run_id=run.id
            )
            seen_types: set = set()
            for step in steps:
                if step.type == "tool_calls":
                    for tc in step.step_details.tool_calls:
                        t = getattr(tc, "type", "")
                        if t and t not in seen_types:
                            seen_types.add(t)
                            tools_used.append({
                                "type":  t,
                                "label": TOOL_LABELS.get(t, t),
                                "color": TOOL_COLORS.get(t, "#6b7280"),
                            })
        except Exception:
            pass
        if tools_used:
            yield {"type": "tools_used", "tools": tools_used}

        # ── stream the response word-by-word ──────────────────
        messages = self.agents_client.messages.list(thread_id=self.thread.id)
        for msg in messages:
            if msg.role != "assistant":
                continue
            for part in msg.content:
                if hasattr(part, "text"):
                    words = part.text.value.split(" ")
                    for i, word in enumerate(words):
                        yield {"type": "text_chunk",
                               "content": word + (" " if i < len(words) - 1 else "")}
                        time.sleep(0.03)
                elif hasattr(part, "image_file"):
                    fid     = part.image_file.file_id
                    fname   = f"chart_{fid}.png"
                    out_dir = Path(__file__).parent / "static" / "charts"
                    out_dir.mkdir(parents=True, exist_ok=True)
                    stream  = self.agents_client.files.get_content(fid)
                    with open(out_dir / fname, "wb") as f:
                        for chunk in stream:
                            f.write(chunk)
                    yield {"type": "image", "url": f"/static/charts/{fname}"}
            break  # only latest assistant message

        yield {"type": "done"}

    # ── private helpers ──────────────────────────────────────

    def _load_config(self) -> dict:
        current = Path(__file__).resolve().parent
        while current != current.parent:
            cand = current / "cred.json"
            if cand.exists():
                with open(cand) as f:
                    return json.load(f)
            current = current.parent
        raise FileNotFoundError("cred.json not found in any parent directory")

