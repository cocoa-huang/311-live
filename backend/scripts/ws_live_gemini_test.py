"""
Step 7.2/7.3 test — connect to /ws/live in vertex mode and send a text message.

Verifies:
- WebSocket session opens
- Gemini receives the text and replies with audio
- Transcription events arrive (what Gemini said)
- If conversation goes far enough, create_report_draft is called

Start the backend first in a separate terminal:
    LIVE_MODEL_MODE=vertex \\
    GOOGLE_CLOUD_PROJECT=live-cloud-495302 \\
    GEMINI_LIVE_MODEL=gemini-live-2.5-flash-preview-native-audio-09-2025 \\
    .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

Then run this script:
    .venv/bin/python -m backend.scripts.ws_live_gemini_test

Exit code 0 = PASS (audio received), 1 = FAIL.
"""

import asyncio
import json
import os
import sys


async def run(ws_url: str, text: str, timeout: float = 20.0) -> bool:
    try:
        import websockets
    except ImportError:
        print("FAIL: websockets not installed")
        return False

    print(f"Connecting to {ws_url} ...")
    try:
        async with websockets.connect(ws_url) as ws:
            print("Connected.")

            # Send start
            await ws.send(json.dumps({"type": "start", "payload": {}}))
            print(f'Sent: start')

            # Give the session a moment to open then send text
            await asyncio.sleep(1.5)
            await ws.send(json.dumps({"type": "text", "text": text}))
            print(f"Sent text: {text!r}")
            print(f"Waiting up to {timeout}s for response...\n")

            audio_total = 0
            deadline = asyncio.get_event_loop().time() + timeout

            while asyncio.get_event_loop().time() < deadline:
                remaining = deadline - asyncio.get_event_loop().time()
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=min(2.0, remaining))
                except asyncio.TimeoutError:
                    continue

                if isinstance(msg, bytes):
                    audio_total += len(msg)
                    print(f"  [audio] {len(msg):>6} bytes  (running total {audio_total})")
                else:
                    data = json.loads(msg)
                    t = data.get("type")
                    if t == "session_ready":
                        print(f"  [event] session_ready  id={data.get('session_id')}")
                    elif t == "transcript":
                        role = data.get("role", "?")
                        text_val = data.get("text", "")
                        finished = data.get("finished", False)
                        tag = "✓" if finished else "~"
                        print(f"  [transcript/{role}] {tag} {text_val!r}")
                    elif t == "turn_complete":
                        print("  [event] turn_complete")
                        if audio_total > 0:
                            break
                    elif t == "draft_ready":
                        report_id = data.get("payload", {}).get("report_id", "?")
                        print(f"  [event] draft_ready  report_id={report_id}")
                        break
                    else:
                        print(f"  [event] {data}")

            print(f"\nTotal audio received: {audio_total} bytes")
            if audio_total > 0:
                print("PASS: Gemini Live session delivered audio over WebSocket.")
                return True
            else:
                print("WARN: No audio received — check server logs for errors.")
                return False

    except ConnectionRefusedError:
        print(f"FAIL: Could not connect to {ws_url}")
        print("      Is the backend running? Start it with:")
        print("        LIVE_MODEL_MODE=vertex GOOGLE_CLOUD_PROJECT=live-cloud-495302 \\")
        print("        .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000")
        return False
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return False


def main() -> None:
    ws_url = os.environ.get("WS_URL", "ws://127.0.0.1:8000/ws/live")
    text = os.environ.get(
        "TEST_TEXT",
        "Hi, I want to report trash bags blocking the sidewalk "
        "at East 7th Street and Avenue A in the East Village.",
    )
    ok = asyncio.run(run(ws_url, text))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
