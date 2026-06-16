import json
from flask import Flask, render_template, request, Response, jsonify, stream_with_context
from agent_core import TravelAgent

app   = Flask(__name__)
agent = TravelAgent()

print("🚀 Initializing Travel Agent...")
try:
    agent.setup()
    print("✅ Travel Agent ready!")
except Exception as e:
    print(f"❌ Agent setup failed: {e}")
# No atexit cleanup — agent persists across restarts (state saved in agent_state.json)


@app.route("/")
def index():
    return render_template("index.html",
                           agent_ready=agent.ready,
                           agent_error=agent.error)


@app.route("/status")
def status():
    return jsonify({"ready": agent.ready, "error": agent.error})


@app.route("/chat", methods=["POST"])
def chat():
    if not agent.ready:
        return jsonify({"error": agent.error or "Agent not ready yet"}), 503

    data     = request.get_json(silent=True) or {}
    question = data.get("message", "").strip()
    if not question:
        return jsonify({"error": "Empty message"}), 400

    @stream_with_context
    def generate():
        try:
            for event in agent.ask_stream(question):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/reset", methods=["POST"])
def reset():
    try:
        agent.reset_thread()
        return jsonify({"status": "ok"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500




if __name__ == "__main__":
    app.run(debug=False, port=5000, threaded=True)
