"""
server/whatsapp_server.py
-------------------------
WhatsApp Cloud API webhook + optional audio STT/TTS bridge to your agent.

Capabilities:
- GET /webhook   : Verify webhook (Meta setup)
- POST /webhook  : Receive messages (text + audio)
- Text -> agent  : Send text reply
- Audio -> STT -> agent : Send text reply (and optional TTS reply back)

IMPORTANT:
- This service calls your LangGraph agent (`src/workflow/graph.py:app`).
- Expose with a tunnel (e.g., Cloudflare Tunnel) in dev for Meta callbacks.
"""

from __future__ import annotations

import os
import io
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

# --- WhatsApp Cloud API config (set in .env) ---
GRAPH_BASE = "https://graph.facebook.com/v20.0"
PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")
GRAPH_TOKEN = os.getenv("WA_GRAPH_TOKEN", "")
VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "macrocomm-verify-token")

# --- Audio settings ---
ENABLE_STT = os.getenv("ENABLE_STT", "true").lower() == "true"
ENABLE_TTS = os.getenv("ENABLE_TTS", "false").lower() == "true"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
TTS_MODEL = os.getenv("TTS_MODEL", "tts_models/en/vctk/vits")  # coqui TTS id

# Ensure runtime/media folders
RUNTIME_DIR = Path("./runtime").resolve()
MEDIA_DIR = RUNTIME_DIR / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

# ---- Import the agent and build a tiny wrapper ----
# We stream the graph and return the last state's "generation" value.
from src.workflow.graph import app as agent_app

def run_agent(question: str) -> str:
    """Run the LangGraph agent and return the final answer text."""
    last = None
    for output in agent_app.stream({"question": question, "documents": [], "web_search": False, "generation": "", "traces": []}):
        for _, value in output.items():
            last = value
    if isinstance(last, dict) and "generation" in last:
        return str(last["generation"])
    return str(last)

# ---- Audio helpers: OGG/OPUS -> WAV16k, STT, TTS ----

def transcode_to_wav16k(input_bytes: bytes) -> bytes:
    """Convert WhatsApp voice (ogg/opus) to 16k mono WAV via ffmpeg."""
    import ffmpeg  # pip install ffmpeg-python

    # Write input to temp file because ffmpeg-python prefers file paths
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=True) as fin, \
         tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as fout:
        fin.write(input_bytes)
        fin.flush()
        (
            ffmpeg
            .input(fin.name)
            .output(fout.name, acodec="pcm_s16le", ac=1, ar="16000")
            .overwrite_output()
            .run(quiet=True)
        )
        fout.seek(0)
        return fout.read()

def stt_transcribe(wav_bytes: bytes) -> str:
    """Transcribe WAV bytes (16k mono) using faster-whisper locally."""
    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as f:
        f.write(wav_bytes)
        f.flush()
        segments, _ = model.transcribe(f.name, beam_size=1)
    text = " ".join([s.text for s in segments]).strip()
    return text or "(no speech detected)"

def tts_synthesize_to_mp3(text: str) -> bytes:
    """Synthesize TTS to MP3 using Coqui TTS model if enabled."""
    if not ENABLE_TTS:
        return b""
    from TTS.api import TTS  # pip install TTS
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as f:
        TTS(model_name=TTS_MODEL).tts_to_file(text=text, file_path=f.name)
        f.seek(0)
        return f.read()

# ---- WhatsApp API helpers ----

async def wa_send_text(to_phone: str, text: str) -> Dict[str, Any]:
    url = f"{GRAPH_BASE}/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {GRAPH_TOKEN}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": text},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()

async def wa_upload_audio(mp3_bytes: bytes) -> Optional[str]:
    """Upload mp3 to WhatsApp and return media_id."""
    url = f"{GRAPH_BASE}/{PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {GRAPH_TOKEN}"}
    files = {"file": ("reply.mp3", mp3_bytes, "audio/mpeg")}
    data = {"messaging_product": "whatsapp"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, data=data, files=files)
        r.raise_for_status()
        return r.json().get("id")

async def wa_send_audio(to_phone: str, media_id: str) -> Dict[str, Any]:
    url = f"{GRAPH_BASE}/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {GRAPH_TOKEN}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "audio",
        "audio": {"id": media_id},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()

# ---- FastAPI app ----

app = FastAPI(title="Macrocomm WhatsApp Webhook", version="1.0")

@app.get("/webhook")
def webhook_verify(hub_mode: str = "", hub_challenge: str = "", hub_verify_token: str = ""):
    """Meta verification handshake."""
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(status_code=403)

@app.post("/webhook")
async def webhook_receive(request: Request):
    """
    Receive WhatsApp messages (text and audio).
    - Text: forward to agent and reply with text
    - Audio: download, transcode, STT, forward transcript to agent, reply with text
    """
    try:
        payload = await request.json()
        # Navigate entry -> changes -> messages
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                if not messages:
                    continue
                from_phone = messages[0].get("from", "")

                msg = messages[0]
                mtype = msg.get("type")
                if mtype == "text":
                    text = (msg.get("text", {}) or {}).get("body", "").strip()
                    if not text:
                        await wa_send_text(from_phone, "Empty message.")
                        continue
                    answer = run_agent(text)
                    await wa_send_text(from_phone, answer)

                elif mtype == "audio" and ENABLE_STT:
                    audio_id = (msg.get("audio", {}) or {}).get("id")
                    if not audio_id:
                        await wa_send_text(from_phone, "Couldn't read audio.")
                        continue
                    # Download audio
                    url_media = f"{GRAPH_BASE}/{audio_id}"
                    headers = {"Authorization": f"Bearer {GRAPH_TOKEN}"}
                    async with httpx.AsyncClient(timeout=60) as client:
                        meta = await client.get(url_media, headers=headers)
                        meta.raise_for_status()
                        media_url = meta.json().get("url")
                        audio = await client.get(media_url, headers=headers)
                        audio.raise_for_status()
                        ogg = audio.content
                    # Transcode + STT
                    wav16 = transcode_to_wav16k(ogg)
                    text = stt_transcribe(wav16)
                    answer = run_agent(text)
                    await wa_send_text(from_phone, answer)

                    # Optional: send TTS reply as audio
                    if ENABLE_TTS:
                        mp3 = tts_synthesize_to_mp3(answer)
                        if mp3:
                            media_id = await wa_upload_audio(mp3)
                            if media_id:
                                await wa_send_audio(from_phone, media_id)
                else:
                    await wa_send_text(from_phone, "Send text or a voice note, please.")

    except Exception as e:
        # Never crash the webhook; log locally and ack 200 so Meta doesn't retry forever
        print("[webhook error]", repr(e))

    return Response(status_code=200)

# --- Dev helpers ---

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/say")
async def say(text: str = "Macrocomm test"):
    if not ENABLE_TTS:
        return JSONResponse({"ok": False, "error": "ENABLE_TTS=false"})
    mp3 = tts_synthesize_to_mp3(text)
    return StreamingResponse(io.BytesIO(mp3), media_type="audio/mpeg")

# Run locally:
# uvicorn server.whatsapp_server:app --host 0.0.0.0 --port 8000 --reload

