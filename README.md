# Kokoro TTS API

Custom FastAPI server that wraps the Kokoro TTS model with native timestamp extraction for SRT subtitle generation.

## Features

- **TTS with native timestamps**: Uses Kokoro's `KPipeline` to generate audio AND extract word-by-word timestamps directly from the model's tokens (zero latency, no extra RAM usage).
- **Automatic SRT generation**: Produces `.srt` files grouped by N words (configurable, default: 2 words = TikTok/Reels style).
- **Base64 Output**: MP3 audio and SRT encoded in base64, ready for n8n or any other HTTP consumer.
- **Smart Memory Management**: Two modes — `on_demand` (loads model per request, frees RAM after) or `persistent` (keeps model in RAM for instant responses).
- **Docker-ready**: A simple `docker compose up` and it's ready.

## Deployment

### Configuration (Environment Variables)

Create a `.env` file at the root of the project by copying the `.env.example` file:

```bash
cp .env.example .env
```

You can configure the API by modifying the `.env` file:

| Variable           | Default                         | Description                                                                 |
| ------------------ | ------------------------------- | --------------------------------------------------------------------------- |
| `API_KEY`          | `change_me_super_secret_key...` | **Required** API key to secure endpoint access (`X-API-Key`).               |
| `KOKORO_LANG_CODE` | `a`                             | Kokoro language code (`a` = US English, `b` = British, `f` = French, etc.). |
| `MODEL_DEVICE`     | `cpu`                           | Inference device (`cpu` by default, can be changed if GPU is available).    |
| `MODEL_MODE`       | `on_demand`                     | `on_demand` = load/unload model per request (~500 Mo idle). `persistent` = keep in RAM (~2-3 Go, instant responses). |

### Launching

```bash
# Upload the kokoro-api folder to your server, then:
cd kokoro-api
docker compose up -d --build
```

The Kokoro model is automatically downloaded on the first run (~1-2 min). The files are cached in a named Docker volume (`kokoro-cache`), so restarts are instant.

## Usage

### Endpoint: `POST /generate_tts`

```bash
curl -X POST http://localhost:8880/generate_tts \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change_me_super_secret_key_123" \
  -d '{
    "input": "Hello, this is a test of the TTS system.",
    "voice": "am_fenrir",
    "speed": 1.0,
    "words_per_sub": 2,
    "lang_code": "a"
  }'
```

### Response

```json
{
  "audio_base64": "...(Base64 encoded MP3)...",
  "srt_base64": "...(Base64 encoded SRT)..."
}
```

### Parameters

| Parameter        | Type    | Default     | Description                                |
|------------------|---------|-------------|--------------------------------------------|
| `input`          | string  | *required*  | The text to synthesize                     |
| `voice`          | string  | `am_fenrir` | The Kokoro voice                           |
| `speed`          | float   | `1.0`       | Speech speed                               |
| `words_per_sub`  | int     | `2`         | Number of words per SRT subtitle           |
| `lang_code`      | string  | *Env default*| Overrides language code (`a`, `b`, etc.) |

### Health Check

```bash
curl http://localhost:8880/health
# {"status": "ok"}
```

### Status (Memory & Mode)

```bash
curl http://localhost:8880/status
# {"status": "ok", "model_mode": "on_demand", "pipelines_loaded": [], "model_in_memory": false}
```

Use this endpoint to check which `MODEL_MODE` is active and whether the model is currently loaded in RAM.

## Architecture

```
kokoro-api/
├── main.py              # FastAPI Server
├── requirements.txt     # Python Dependencies
├── Dockerfile           # Docker Image
├── docker-compose.yml   # Orchestration
└── README.md            # This file
```
