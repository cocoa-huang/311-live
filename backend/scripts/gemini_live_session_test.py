"""
Step 7.1 — Validate Gemini Live model access.

Tries to open a live_connect() session, send a text probe, and receive a
text response. Run this before building any audio pipeline.

Usage — Vertex ADC (try first):
    GOOGLE_CLOUD_PROJECT=your-project \
    GEMINI_LIVE_MODEL=gemini-live-2.5-flash-preview-native-audio-09-2025 \
    GEMINI_LIVE_LOCATION=us-central1 \
    .venv/bin/python -m backend.scripts.gemini_live_session_test

Usage — Google AI Studio API key (if Vertex returns 403 or model-not-found):
    GOOGLE_API_KEY=your-key \
    GEMINI_LIVE_MODEL=gemini-2.0-flash-live-001 \
    .venv/bin/python -m backend.scripts.gemini_live_session_test --api-key

Exit code 0 = PASS, 1 = FAIL.
"""

import argparse
import asyncio
import os
import sys

TIMEOUT_SECONDS = 30
DEFAULT_LIVE_MODEL_VERTEX = "gemini-live-2.5-flash-preview-native-audio-09-2025"
DEFAULT_LIVE_MODEL_API_KEY = "gemini-2.0-flash-live-001"


async def run(use_api_key: bool, model: str, project: str | None, location: str) -> bool:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("FAIL: google-genai is not installed.")
        print("      Run: .venv/bin/pip install google-genai==1.74.0")
        return False

    if use_api_key:
        api_key = os.environ.get("GOOGLE_API_KEY", "")
        if not api_key:
            print("FAIL: GOOGLE_API_KEY is not set.")
            return False
        client = genai.Client(api_key=api_key)
        print(f"Auth : Google AI Studio (API key)")
    else:
        if not project:
            print("FAIL: GOOGLE_CLOUD_PROJECT is not set.")
            print("      Set it or run with --api-key to use Google AI Studio instead.")
            return False
        client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
        )
        print(f"Auth : Vertex AI  project={project}  location={location}")

    print(f"Model: {model}")
    print("Opening Gemini Live session...")

    # Native audio model only supports AUDIO output — TEXT modality is rejected.
    config = types.LiveConnectConfig(response_modalities=["AUDIO"])

    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            async with client.aio.live.connect(model=model, config=config) as session:
                print("Session open. Sending probe message...")
                await session.send_client_content(
                    turns={"role": "user", "parts": [{"text": "Say hello."}]},
                    turn_complete=True,
                )
                print("Waiting for audio response...")
                audio_bytes = 0
                async for msg in session.receive():
                    if msg.server_content and msg.server_content.model_turn:
                        for part in msg.server_content.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                audio_bytes += len(part.inline_data.data)
                    if msg.server_content and msg.server_content.turn_complete:
                        break

        print(f"\nGemini returned {audio_bytes} bytes of audio.")
        if audio_bytes == 0:
            print("WARN: Session connected but received no audio bytes — model may have been silent.")
        else:
            print("PASS: Live session connected and returned audio.")
        return True

    except TimeoutError:
        print(f"\nFAIL: No response within {TIMEOUT_SECONDS}s.")
        return False
    except Exception as exc:
        print(f"\nFAIL: {type(exc).__name__}: {exc}")
        print("\nCommon causes:")
        print("  403 / permission denied  → model not enabled in this project, or ADC not set up")
        print("  404 / model not found    → model name wrong or not available in this region")
        print("  ImportError              → google-genai not installed in the active venv")
        print("\nIf Vertex fails, retry with --api-key after setting GOOGLE_API_KEY.")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Gemini Live model access (Step 7.1).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--api-key",
        action="store_true",
        help="Use GOOGLE_API_KEY (Google AI Studio) instead of Vertex ADC.",
    )
    args = parser.parse_args()

    default_model = DEFAULT_LIVE_MODEL_API_KEY if args.api_key else DEFAULT_LIVE_MODEL_VERTEX
    model = os.environ.get("GEMINI_LIVE_MODEL", default_model)
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GEMINI_LIVE_LOCATION", "us-central1")

    ok = asyncio.run(run(args.api_key, model, project, location))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
