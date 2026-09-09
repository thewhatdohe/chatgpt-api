# Adam Chat Bot Ultra

A lightweight chat UI built with Flask that sits in front of a chat backend.

The UI is served from `templates/index.html`, with `app.py` acting as a small API shim between the browser and the backend.

```text
browser ──▶ shim :5100 ──▶ chat backend
                       └──▶ vision backend (for images)
```

## Running it

The current setup uses a local codex-oauth bridge on `:10531` for chat. Since that backend doesn't handle images, Gemini is used for image understanding.

Set the Gemini API key:

```bash
export VISION_API_KEY='your-gemini-key'
```

Then start the app:

```bash
python3 app.py
```

Open `http://localhost:5100`.

## Images

Images can be pasted into the composer with **Ctrl+V**.

When the chat backend doesn't support images, the shim sends the image to the configured vision backend first. The resulting description is then passed to the chat backend as text.

Image descriptions are cached, so the same image doesn't need to be processed again during the conversation.

If the configured chat backend supports images natively, images are passed through directly instead.

Pasted images are resized to a maximum dimension of 1568px before being stored or sent.

## Chat history

Chat history is stored in the browser using `localStorage`.

There is no database or server-side conversation storage. Images attached to conversations are stored there as well.

If the browser runs out of storage space, the UI will indicate that the history could not be saved.

## Configuration

| Variable         | Default                           | Description                                       |
| ---------------- | --------------------------------- | ------------------------------------------------- |
| `LOCAL_API_URL`  | `http://127.0.0.1:10531/v1`       | Chat backend URL                                  |
| `LOCAL_API_KEY`  | none                              | Chat backend bearer token                         |
| `DEFAULT_MODEL`  | `gpt-5.4-mini`                    | Default model                                     |
| `FALLBACK_MODEL` | `gpt-5.6-terra`                   | Fallback when the requested model isn't available |
| `VISION_API_URL` | Gemini OpenAI-compatible endpoint | Vision backend URL                                |
| `VISION_API_KEY` | none                              | Vision backend API key                            |
| `VISION_MODEL`   | `gemini-2.0-flash`                | Vision model                                      |
| `HOST`           | `127.0.0.1`                       | Listen address                                    |
| `PORT`           | `5100`                            | Listen port                                       |

Image support requires `VISION_API_KEY` to be set.

## Backend setup

The default configuration assumes the chat backend is running locally on port `10531`.

The vision backend is only used when the configured chat backend can't receive images. This makes it possible to use the same UI with either an image-capable provider or an image-blind local backend.

## LobeChat

The previous LobeChat container setup has been retired. The old `podman run` command is still available in the git history if needed.
