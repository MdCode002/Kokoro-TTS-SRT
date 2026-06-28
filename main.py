"""
Kokoro TTS API Server
=====================
FastAPI server that wraps Kokoro TTS pipeline.
- Generates audio from text
- Extracts word-level timestamps from native Kokoro tokens
- Produces SRT subtitles (2 words per line, TikTok style)
- Returns audio (MP3) and SRT as base64
"""

import os
import io
import base64
import subprocess
import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_403_FORBIDDEN
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from kokoro import KPipeline

app = FastAPI(
    title="Kokoro TTS API",
    description="Custom TTS API with native word-level timestamps and SRT generation",
    version="1.0.0",
)

# Configuration via Environment Variables
API_KEY = os.environ.get("API_KEY", "change_me_in_docker_compose")
LANG_CODE = os.environ.get("KOKORO_LANG_CODE", "a")  # a: American, b: British, f: French, etc.
DEVICE = os.environ.get("MODEL_DEVICE", "cpu")

# API Key Security
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def get_api_key(api_key_header: str = Security(api_key_header)):
    if API_KEY and api_key_header != API_KEY:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN, detail="Invalid or missing API Key."
        )
    return api_key_header

# Pipeline Management (Multi-language)
# Cache initialized pipelines to avoid reloading them on every request
pipelines_cache: dict[str, KPipeline] = {}

def get_pipeline(lang_code: str) -> KPipeline:
    if lang_code not in pipelines_cache:
        pipelines_cache[lang_code] = KPipeline(lang_code=lang_code, device=DEVICE)
    return pipelines_cache[lang_code]


# Models
class TTSRequest(BaseModel):
    input: str
    voice: str = "am_fenrir"
    speed: float = 1.0
    words_per_sub: int = 2  # Number of words per SRT subtitle
    lang_code: str | None = None  # Override default language (a, b, f, etc.)


class TTSResponse(BaseModel):
    audio_base64: str
    srt_base64: str


# Helpers
def ms_to_srt_time(ms: int) -> str:
    seconds, milliseconds = divmod(int(ms), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def extract_words(tokens, chunk_offset_seconds: float) -> tuple[list[dict], float]:
    words = []
    current_text: list[str] = []
    current_start: float | None = None
    current_end: float | None = None
    last_end = chunk_offset_seconds

    for token in tokens or []:
        text = getattr(token, "text", "")
        if not text:
            continue

        start_ts = getattr(token, "start_ts", None)
        end_ts = getattr(token, "end_ts", None)

        if current_start is None and start_ts is not None:
            current_start = chunk_offset_seconds + float(start_ts)
        if end_ts is not None:
            current_end = chunk_offset_seconds + float(end_ts)

        current_text.append(text)

        if getattr(token, "whitespace", ""):
            word_text = "".join(current_text).strip()
            if word_text:
                start = current_start if current_start is not None else last_end
                end = current_end if current_end is not None else start
                words.append({
                    "text": word_text,
                    "startMs": round(start * 1000),
                    "endMs": round(end * 1000),
                })
                last_end = end

            current_text = []
            current_start = None
            current_end = None

    remaining = "".join(current_text).strip()
    if remaining:
        start = current_start if current_start is not None else last_end
        end = current_end if current_end is not None else start
        words.append({
            "text": remaining,
            "startMs": round(start * 1000),
            "endMs": round(end * 1000),
        })
        last_end = end

    return words, last_end


def words_to_srt(words: list[dict], words_per_sub: int = 2) -> str:
    srt_lines: list[str] = []
    idx = 1
    i = 0

    while i < len(words):
        group = words[i : i + words_per_sub]
        start_ms = group[0]["startMs"]
        end_ms = group[-1]["endMs"]

        if end_ms <= start_ms:
            end_ms = start_ms + 100

        srt_lines.append(str(idx))
        srt_lines.append(f"{ms_to_srt_time(start_ms)} --> {ms_to_srt_time(end_ms)}")
        srt_lines.append(" ".join(w["text"] for w in group))
        srt_lines.append("")

        idx += 1
        i += words_per_sub

    return "\n".join(srt_lines)


def wav_to_mp3(audio: np.ndarray, sample_rate: int = 24000) -> bytes:
    wav_buf = io.BytesIO()
    sf.write(wav_buf, audio, sample_rate, format="WAV")
    wav_bytes = wav_buf.getvalue()

    proc = subprocess.run(
        [
            "ffmpeg",
            "-i", "pipe:0",
            "-f", "mp3",
            "-ab", "128k",
            "-ac", "1",
            "-ar", str(sample_rate),
            "-v", "error",
            "pipe:1",
        ],
        input=wav_bytes,
        capture_output=True,
    )

    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {proc.stderr.decode()}")

    return proc.stdout


# Main Endpoint
@app.post("/generate_tts", response_model=TTSResponse)
def generate_tts(req: TTSRequest, api_key: str = Depends(get_api_key)):
    """
    Generates TTS audio + SRT subtitles from text.
    """
    if not req.input or not req.input.strip():
        raise HTTPException(status_code=400, detail="The 'input' field cannot be empty.")

    try:
        request_lang = req.lang_code if req.lang_code else LANG_CODE
        pipeline = get_pipeline(request_lang)

        results = list(
            pipeline(req.input, voice=req.voice, speed=req.speed, split_pattern=r"\n+")
        )

        all_words: list[dict] = []
        audio_chunks: list[np.ndarray] = []
        chunk_offset = 0.0

        for res in results:
            words, _ = extract_words(res.tokens, chunk_offset)
            all_words.extend(words)

            if res.audio is not None:
                audio_chunks.append(res.audio)
                chunk_offset += len(res.audio) / 24000

        if not audio_chunks:
            raise HTTPException(status_code=500, detail="No audio generated by Kokoro.")

        full_audio = np.concatenate(audio_chunks)

        srt_content = words_to_srt(all_words, req.words_per_sub)

        mp3_bytes = wav_to_mp3(full_audio, sample_rate=24000)
        audio_b64 = base64.b64encode(mp3_bytes).decode("utf-8")
        srt_b64 = base64.b64encode(srt_content.encode("utf-8")).decode("utf-8")

        return JSONResponse({
            "audio_base64": audio_b64,
            "srt_base64": srt_b64,
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Health check
@app.get("/health")
def health():
    return {"status": "ok"}
