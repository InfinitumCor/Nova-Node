# nova_websocket.py
# WebSocket bridge — local desktop HUD only.
#
# Public release strips mobile/remote access. Bound to loopback only
# (config.WEBSOCKET_HOST defaults to 127.0.0.1). Handshake takes no
# token. Build your own HUD against this surface.
#
# Outbound message types (sent to the connected HUD):
#   {"type": "state",      "state": "idle"|"listening"|"thinking"|"speaking"}
#   {"type": "transcript", "role": "user"|"nova", "text": str}
#   {"type": "metrics",    "data": {...}}
#   {"type": "emotion",    "snapshot": {...}}
#
# Inbound message types (received from the HUD):
#   {"type": "user_input", "text": str}                — typed input
#   {"type": "ping"}                                   — keepalive

import asyncio
import json
import threading
from typing import Optional

from config import config


_server = None
_clients: dict = {}      # websocket -> {"type": "desktop"}
_loop: Optional[asyncio.AbstractEventLoop] = None
_thread: Optional[threading.Thread] = None
_current_state = "idle"

# Inbound queues drained by nova.py
_pending_input: list[str] = []
_pending_input_lock = threading.Lock()


# ── Public API ──────────────────────────────────────────────────

def start_server():
    """Launch the WebSocket server in a background thread."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_run_server, daemon=True)
    _thread.start()


def stop_server():
    """Shut down the server (best-effort)."""
    global _server
    if _server is not None and _loop is not None:
        try:
            _loop.call_soon_threadsafe(_server.close)
        except Exception:
            pass


def get_pending_input() -> list[str]:
    """Drain any queued user_input messages from the HUD."""
    with _pending_input_lock:
        out, _pending_input[:] = list(_pending_input), []
    return out


def emit_to_desktop(payload: dict, **_kwargs) -> None:
    """Broadcast a message to all connected desktop clients."""
    if _loop is None or not _clients:
        return
    try:
        asyncio.run_coroutine_threadsafe(_broadcast(payload), _loop)
    except Exception as e:
        print(f"[WebSocket] emit error: {e}")


def emit_state(state: str) -> None:
    """Push a new state to the HUD."""
    global _current_state
    _current_state = state
    emit_to_desktop({"type": "state", "state": state})


def emit_transcript(role: str, text: str) -> None:
    """Push a transcript line to the HUD."""
    emit_to_desktop({"type": "transcript", "role": role, "text": text})


def emit_metrics(data: dict) -> None:
    """Push a metrics snapshot to the HUD."""
    emit_to_desktop({"type": "metrics", "data": data})


def emit_emotion(snapshot: dict) -> None:
    """Push an emotion engine snapshot to the HUD."""
    emit_to_desktop({"type": "emotion", "snapshot": snapshot})


def emit_task_activity(*args, **kwargs) -> None:
    """No-op stub for parity with Prime callers."""
    return None


# ── Internals ──────────────────────────────────────────────────

def _run_server():
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _loop.run_until_complete(_serve())


async def _serve():
    import websockets
    global _server
    _server = await websockets.serve(
        _handler,
        config.WEBSOCKET_HOST,
        config.WEBSOCKET_PORT,
    )
    print(f"[WebSocket] Server running on ws://{config.WEBSOCKET_HOST}:{config.WEBSOCKET_PORT}")
    await asyncio.Future()  # run forever


async def _broadcast(payload: dict):
    if not _clients:
        return
    msg = json.dumps(payload, default=str)
    dead = []
    for ws in list(_clients.keys()):
        try:
            await ws.send(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.pop(ws, None)


async def _handler(websocket):
    """Handle a single client connection. No auth — loopback-only."""
    _clients[websocket] = {"type": "desktop"}
    print(f"[WebSocket] Client connected ({len(_clients)} total)")

    try:
        await websocket.send(json.dumps({"type": "state", "state": _current_state}))
    except Exception:
        pass

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except Exception:
                continue

            msg_type = data.get("type", "")

            if msg_type == "handshake":
                # No-op; loopback connections are trusted.
                try:
                    await websocket.send(json.dumps({"type": "auth_ok"}))
                except Exception:
                    pass
                continue

            if msg_type == "user_input":
                text = data.get("text", "")
                if text:
                    with _pending_input_lock:
                        _pending_input.append(text)
                continue

            if msg_type == "ping":
                try:
                    await websocket.send(json.dumps({"type": "pong"}))
                except Exception:
                    pass
                continue

            # Unknown types — silently ignore
    except Exception as e:
        print(f"[WebSocket] Handler error: {e}")
    finally:
        _clients.pop(websocket, None)
        print(f"[WebSocket] Client disconnected ({len(_clients)} total)")
