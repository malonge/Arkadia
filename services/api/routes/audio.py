"""WebSocket endpoint for the real-time audio stream.

Route:
    GET /ws/audio/stream  — WebSocket; streams AudioStreamPayload frames at ~20 Hz
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws/audio/stream")
async def audio_stream(websocket: WebSocket, api_key: str = "") -> None:
    """Stream real-time AudioStreamPayload frames to the caller.

    Authentication is via the ``api_key`` query parameter (e.g.
    ``ws://host:8000/ws/audio/stream?api_key=<key>``).

    Frames arrive at approximately 20 Hz while the audio service is
    producing data.  The connection is kept open until the client
    disconnects.
    """
    expected_key: str = websocket.app.state.api_key
    if api_key != expected_key:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    broadcaster = websocket.app.state.broadcaster
    await websocket.accept()
    broadcaster.add(websocket)
    logger.info(
        "WebSocket client connected to audio stream",
        extra={"event": "ws_audio_connected"},
    )

    try:
        while True:
            # Keep the connection alive; frames are pushed via broadcaster.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.remove(websocket)
        logger.info(
            "WebSocket client disconnected from audio stream",
            extra={"event": "ws_audio_disconnected"},
        )
