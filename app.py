import hashlib
import json
import os
import time

import requests
from flask import Flask, Response, jsonify, render_template, request

app = Flask(__name__)
# re-read templates/index.html on each request so UI edits show on refresh
# (this is a local tool; the tiny stat() cost per request is irrelevant)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

# --- chat backend (OpenAI-compatible; no trailing /chat/completions) ---------
UPSTREAM = os.environ.get("LOCAL_API_URL", "http://127.0.0.1:10531/v1").rstrip("/")
if UPSTREAM.endswith("/chat/completions"):
  UPSTREAM = UPSTREAM[: -len("/chat/completions")]

API_KEY = os.environ.get("LOCAL_API_KEY", "")
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "gpt-5.6-terra")
# Model substituted when a UI asks for one the backend does not serve.
FALLBACK_MODEL = os.environ.get("FALLBACK_MODEL", "gpt-5.6-terra")

# --- vision backend ---------------------------------------------------------
# The codex-oauth bridge cannot take images: it rejects data: URLs and fetches
# http ones from upstream, which cannot reach this machine. So when the chat
# backend is image-blind we hand the picture to a vision model first and send
# its description along as text. Any OpenAI-compatible vision endpoint works.
VISION_URL = os.environ.get(
    "VISION_API_URL", "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
VISION_KEY = os.environ.get("VISION_API_KEY", "")
VISION_MODEL = os.environ.get("VISION_MODEL", "gemini-3.6-flash")

# A loopback chat backend is the local bridge, which is image-blind.
CHAT_IS_IMAGE_BLIND = "127.0.0.1" in UPSTREAM or "localhost" in UPSTREAM

DESCRIBE_PROMPT = (
    "Describe this image in thorough detail so someone who cannot see it could "
    "reason about it. Transcribe ALL visible text exactly, including code, error "
    "messages, labels and numbers, preserving line breaks. Note layout, colors, "
    "UI elements, and anything that looks like a problem or an anomaly. Do not "
    "add commentary or interpretation beyond what is visibly present."
)

# One description per distinct image, reused across turns so a long
# conversation does not re-bill (and re-rate-limit) the same screenshot.
_vision_cache = {}
_model_cache = {"ids": [], "at": 0.0}


def upstream_headers():
  headers = {"Content-Type": "application/json"}
  if API_KEY:
    headers["Authorization"] = "Bearer " + API_KEY
  return headers


def sse(event):
  return "data: " + json.dumps(event) + "\n\n"


# --- model handling ---------------------------------------------------------
def known_models():
  """Model ids the backend actually serves, cached for a minute."""
  now = time.time()
  if _model_cache["ids"] and now - _model_cache["at"] < 60:
    return _model_cache["ids"]
  try:
    r = requests.get(UPSTREAM + "/models", headers=upstream_headers(), timeout=10)
    ids = [m.get("id") for m in r.json().get("data", []) if m.get("id")]
  except Exception:
    ids = []
  if ids:
    _model_cache.update({"ids": ids, "at": now})
  return ids


def resolve_model(requested):
  """Map an unknown model id onto one the backend supports."""
  ids = known_models()
  if not ids or requested in ids:
    return requested, False
  if FALLBACK_MODEL in ids:
    return FALLBACK_MODEL, True
  return ids[0], True


# --- vision -----------------------------------------------------------------
class VisionError(Exception):
  pass


def describe_image(data_url):
  """Send one image to the vision model and return its description."""
  key = hashlib.sha256(data_url.encode()).hexdigest()
  if key in _vision_cache:
    return _vision_cache[key]

  if not VISION_KEY:
    raise VisionError(
        "An image was sent but no vision backend is configured. Set "
        "VISION_API_KEY (and optionally VISION_MODEL) to enable image support.")

  payload = {
      "model": VISION_MODEL,
      "messages": [{"role": "user", "content": [
          {"type": "text", "text": DESCRIBE_PROMPT},
          {"type": "image_url", "image_url": {"url": data_url}},
      ]}],
  }
  try:
    r = requests.post(VISION_URL + "/chat/completions",
                      headers={"Content-Type": "application/json",
                               "Authorization": "Bearer " + VISION_KEY},
                      json=payload, timeout=(10, 180))
  except requests.exceptions.RequestException as e:
    raise VisionError("Could not reach the vision model: " + str(e))

  if r.status_code >= 400:
    raise VisionError("Vision model returned HTTP " + str(r.status_code) +
                      ": " + r.text[:300])
  try:
    text = r.json()["choices"][0]["message"]["content"]
  except (ValueError, KeyError, IndexError):
    raise VisionError("Unexpected reply from the vision model: " + r.text[:300])

  text = (text or "").strip()
  if not text:
    raise VisionError("The vision model returned an empty description.")
  _vision_cache[key] = text
  return text


def flatten_images(messages):
  """Replace image parts with vision descriptions so a text-only backend copes.

  Returns the number of images translated. Mutates `messages` in place.
  """
  translated = 0
  for msg in messages:
    content = msg.get("content")
    if not isinstance(content, list):
      continue

    chunks = []
    seen = 0
    for part in content:
      if not isinstance(part, dict):
        continue
      if part.get("type") == "text":
        if part.get("text"):
          chunks.append(part["text"])
      elif part.get("type") == "image_url":
        url = (part.get("image_url") or {}).get("url", "")
        if not url:
          continue
        seen += 1
        translated += 1
        desc = describe_image(url)
        chunks.append("[Attached image " + str(seen) + " — description from a "
                      "vision model:\n" + desc + "\n]")
    msg["content"] = "\n\n".join(chunks)
  return translated


def prepare(messages):
  """Apply the vision stage when the chat backend cannot see images."""
  if CHAT_IS_IMAGE_BLIND:
    return flatten_images(messages)
  return 0


# --- routes -----------------------------------------------------------------
@app.route("/")
def index():
  return render_template("index.html")


@app.route("/api/config")
def config():
  return jsonify({"default_model": DEFAULT_MODEL, "upstream": UPSTREAM,
                  "vision": bool(VISION_KEY), "vision_model": VISION_MODEL})


@app.route("/api/models")
def models():
  ids = known_models()
  if DEFAULT_MODEL not in ids:
    ids = [DEFAULT_MODEL] + ids
  return jsonify({"models": ids, "default": DEFAULT_MODEL})


def open_upstream(payload):
  """POST to the chat backend, retrying once on FALLBACK_MODEL if the requested
  model is rejected. The backend's /models list advertises models the account
  cannot actually use (e.g. gpt-5.4-mini on a ChatGPT-account Codex), which come
  back as a 4xx/5xx; the retry keeps a bad pick from dead-ending the user."""
  r = requests.post(UPSTREAM + "/chat/completions", headers=upstream_headers(),
                    json=payload, stream=True, timeout=(10, 600))
  if r.status_code >= 400 and payload.get("model") != FALLBACK_MODEL:
    app.logger.warning("model %r rejected (HTTP %s); retrying with %r",
                       payload.get("model"), r.status_code, FALLBACK_MODEL)
    r.close()
    payload = dict(payload, model=FALLBACK_MODEL)
    r = requests.post(UPSTREAM + "/chat/completions", headers=upstream_headers(),
                      json=payload, stream=True, timeout=(10, 600))
  return r


@app.route("/api/chat", methods=["POST"])
def proxy_chat():
  """Stream a completion back to the browser as Server-Sent Events."""
  body = request.get_json(silent=True) or {}
  messages = body.get("messages", [])

  try:
    prepare(messages)
  except VisionError as e:
    return Response(sse({"error": str(e)}) + "data: [DONE]\n\n",
                    mimetype="text/event-stream")

  payload = {"model": body.get("model") or DEFAULT_MODEL,
             "messages": messages, "stream": True}
  for key in ("temperature", "top_p", "max_tokens"):
    if body.get(key) is not None:
      payload[key] = body[key]

  def generate():
    # A model the account cannot use does not fail with a clean status: the
    # backend opens a 200 stream and then aborts it ("Response ended
    # prematurely"). So retry on FALLBACK_MODEL whenever the stream produces no
    # content, whether it failed by status or mid-stream, as long as we have
    # not emitted anything to the browser yet.
    attempt = payload
    tried_fallback = (attempt.get("model") == FALLBACK_MODEL)
    while True:
      produced = False
      try:
        r = requests.post(UPSTREAM + "/chat/completions", headers=upstream_headers(),
                          json=attempt, stream=True, timeout=(10, 600))
        try:
          if r.status_code >= 400:
            if not tried_fallback:
              app.logger.warning("model %r rejected (HTTP %s); retrying with %r",
                                 attempt.get("model"), r.status_code, FALLBACK_MODEL)
              tried_fallback = True
              attempt = dict(attempt, model=FALLBACK_MODEL)
              continue
            yield sse({"error": "Upstream " + str(r.status_code) + ": " + r.text[:500]})
            return

          # Some backends ignore stream=True and answer with one JSON blob.
          if "text/event-stream" not in r.headers.get("Content-Type", ""):
            data = r.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if text:
              yield sse({"delta": text})
              produced = True
            yield "data: [DONE]\n\n"
            return

          for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
              continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
              break
            try:
              data = json.loads(chunk)
            except ValueError:
              continue
            for choice in data.get("choices", []):
              piece = (choice.get("delta") or {}).get("content")
              if piece:
                yield sse({"delta": piece})
                produced = True
          yield "data: [DONE]\n\n"
          return
        finally:
          r.close()

      except requests.exceptions.ConnectionError:
        yield sse({"error": "Could not reach the chat backend at " + UPSTREAM +
                   ". Is it running?"})
        return
      except Exception as e:  # noqa: BLE001  (incl. ChunkedEncodingError)
        # a mid-stream abort before any token usually means a bad model
        if not produced and not tried_fallback:
          app.logger.warning("stream aborted for model %r (%s); retrying with %r",
                             attempt.get("model"), type(e).__name__, FALLBACK_MODEL)
          tried_fallback = True
          attempt = dict(attempt, model=FALLBACK_MODEL)
          continue
        if not produced:
          yield sse({"error": str(e)})
        return

  return Response(generate(), mimetype="text/event-stream",
                  headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/v1/models", methods=["GET"])
def v1_models():
  try:
    r = requests.get(UPSTREAM + "/models", headers=upstream_headers(), timeout=10)
    return Response(r.content, status=r.status_code,
                    content_type=r.headers.get("Content-Type", "application/json"))
  except Exception as e:  # noqa: BLE001
    return jsonify({"error": {"message": str(e)}}), 502


@app.route("/v1/chat/completions", methods=["POST"])
def v1_chat_completions():
  """OpenAI-compatible route, for off-the-shelf UIs."""
  body = request.get_json(silent=True) or {}

  try:
    prepare(body.get("messages", []))
  except VisionError as e:
    return jsonify({"error": {"message": str(e),
                              "type": "invalid_request_error"}}), 400

  chosen, swapped = resolve_model(body.get("model"))
  if swapped:
    app.logger.warning("model %r not on backend; using %r", body.get("model"), chosen)
    body["model"] = chosen

  try:
    r = open_upstream(body)
  except requests.exceptions.ConnectionError:
    return jsonify({"error": {"message": "Cannot reach the backend at " + UPSTREAM}}), 502

  def relay():
    try:
      for chunk in r.iter_content(chunk_size=None):
        if chunk:
          yield chunk
    finally:
      r.close()

  return Response(relay(), status=r.status_code,
                  content_type=r.headers.get("Content-Type", "application/json"),
                  headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
  # threaded=True matters: each streaming response holds a connection open.
  app.run(host=os.environ.get("HOST", "127.0.0.1"),
          port=int(os.environ.get("PORT", 5100)), threaded=True)
