# Adam Chat Bot Ultra

A lean chat UI (`templates/index.html`) served by a small Flask shim (`app.py`)
that sits in front of your chat backend. Chat history lives in the browser
(localStorage), so there is no database and nothing to run but the shim.

```
browser ──▶ shim :5100 ──▶ chat backend      (text)
                       └──▶ vision backend    (only when an image is sent
                                                and the chat backend is blind)
```

## Run it

```bash
# chat backend = your local codex-oauth bridge on :10531 (image-blind)
# vision backend = Gemini (free tier) for image understanding
export VISION_API_KEY='your-gemini-key'        # set in YOUR shell; keep it out of the code
python3 app.py
```

Open <http://localhost:5100>.

## Why the split

The codex-oauth bridge on `:10531` cannot accept images — it rejects inline
`data:` URLs and fetches http ones from upstream, which cannot reach this
machine (and over Tor cannot reach a `data:`/local URL at all). GPT-5 the model
supports vision; that bridge does not deliver the bytes to it.

So when the chat backend is image-blind (a loopback URL), the shim sends any
pasted image to a **vision backend** first, gets a detailed text description
(all visible text transcribed), and passes that along with your prompt as text.
The chat model then reasons over the description. Each distinct image is
described once and cached, so a long conversation does not re-bill the same
screenshot.

If you point the chat backend at a provider that sees images natively (OpenAI,
Gemini), the shim detects the non-loopback URL and passes images straight
through — no vision hop.

## Environment

| var | default | meaning |
|---|---|---|
| `LOCAL_API_URL` | `http://127.0.0.1:10531/v1` | chat backend base URL |
| `LOCAL_API_KEY` | (none) | bearer token for the chat backend |
| `DEFAULT_MODEL` | `gpt-5.4-mini` | model offered to the UI |
| `FALLBACK_MODEL` | `gpt-5.6-terra` | substituted when a UI asks for a model the backend lacks |
| `VISION_API_URL` | Gemini OpenAI-compat endpoint | vision backend base URL |
| `VISION_API_KEY` | (none) | key for the vision backend; **images are disabled until this is set** |
| `VISION_MODEL` | `gemini-2.0-flash` | vision model id |
| `HOST` / `PORT` | `127.0.0.1` / `5100` | where the shim listens |

Get a free Gemini key at <https://aistudio.google.com> (no card). Free tier has
rate limits and is not covered by paid-tier data-use guarantees — fine for
personal use, but it is not private.

## Images

- Paste with **Ctrl+V** in the composer. Thumbnails appear above the input;
  click × to remove one. Send works with an image alone (no text needed).
- Pasted images are downscaled (longest side ≤ 1568px) before being stored or
  sent, to fit the browser's storage quota and keep vision cost down.
- Chat history (including images) is per-browser-profile in localStorage. If it
  ever fills up, the status line says "History not saved (storage full)".

## The old LobeChat container

Retired. If you ever want it back, the `podman run` command is in the git
history of this file / your notes; it is not part of this stack anymore.
