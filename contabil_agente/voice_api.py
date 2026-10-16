"""FastAPI WebSocket streaming scaffold for real-time voice delivery.

Provides a WebSocket endpoint clients can use to request TTS/STT
work and receive persona typing/ speaking events and audio chunks
in real time. Uses Celery tasks when available; otherwise runs
work in threads to avoid blocking the event loop.

Usage (simple): connect to `ws://.../ws/voice/{session_id}` and
send JSON messages like:
  {"action":"synthesize","text":"Olá Maria Helena","stream":true}
Server will emit status events and then stream bytes for the audio file.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from contabil_agente.tasks.voice_tasks import (
    synthesize_audio_task,
    transcribe_file_task,
)
from contabil_agente.tools.voz_tool import ToolVoz

app = FastAPI()
_voc = ToolVoz()


@app.get("/health")
async def health():
    return _voc.health()


@app.websocket("/ws/voice/{session_id}")
async def ws_voice(websocket: WebSocket, session_id: str):
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                await websocket.send_json({"event": "error", "message": "invalid json"})
                continue

            action = msg.get("action")

            if action == "synthesize":
                text = msg.get("text", "")
                filename = msg.get("filename")
                stream_bytes = bool(msg.get("stream", False))

                # notify frontend persona is 'typing' / 'speaking'
                # If client requested streaming, use ToolVoz.stream_mp3 directly
                if stream_bytes:
                    await websocket.send_json(
                        {"event": "persona_typing", "status": True}
                    )
                    try:
                        # notify MIME ahead of first binary frame
                        await websocket.send_json(
                            {"event": "audio_mime", "mime": "audio/mpeg"}
                        )
                        async for chunk in _voc.stream_mp3(text):
                            await websocket.send_bytes(chunk)
                        await websocket.send_json({"event": "audio_stream_end"})
                    except Exception as e:
                        await websocket.send_json(
                            {"event": "error", "message": f"stream failed: {e}"}
                        )
                    finally:
                        await websocket.send_json(
                            {"event": "persona_typing", "status": False}
                        )
                    continue

                # Otherwise fall back to background task that produces a file
                await websocket.send_json({"event": "persona_typing", "status": True})

                # Prefer Celery background task if available
                if hasattr(synthesize_audio_task, "delay"):
                    task = synthesize_audio_task.delay(session_id, text, filename)

                    # simple poll loop for task completion
                    while not task.ready():
                        await asyncio.sleep(0.4)
                    result = task.get(timeout=1)
                else:
                    # run off-thread to avoid blocking
                    result = await asyncio.to_thread(
                        synthesize_audio_task, session_id, text, filename
                    )

                await websocket.send_json({"event": "persona_typing", "status": False})

                if not isinstance(result, dict):
                    await websocket.send_json(
                        {"event": "error", "message": "invalid task response"}
                    )
                    continue

                if result.get("status") != "success":
                    await websocket.send_json(
                        {"event": "error", "message": result.get("message", "unknown")}
                    )
                    continue

                filepath = result.get("filepath")
                await websocket.send_json(
                    {"event": "audio_ready", "filepath": filepath}
                )

            elif action == "transcribe":
                audio_path = msg.get("audio_path")
                language = msg.get("language", "pt-BR")
                await websocket.send_json({"event": "processing", "step": "transcribe"})

                if hasattr(transcribe_file_task, "delay"):
                    task = transcribe_file_task.delay(audio_path, language)
                    while not task.ready():
                        await asyncio.sleep(0.4)
                    result = task.get(timeout=1)
                else:
                    result = await asyncio.to_thread(
                        transcribe_file_task, audio_path, language
                    )

                await websocket.send_json(
                    {"event": "transcription_result", "result": result}
                )

            else:
                await websocket.send_json(
                    {"event": "error", "message": "unknown action"}
                )

    except WebSocketDisconnect:
        # client disconnected; nothing to do
        return
