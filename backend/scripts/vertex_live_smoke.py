import argparse
import asyncio

from backend.agents.live_model import LiveObservation, live_model_adapter_from_settings
from backend.settings import Settings


async def run_smoke(
    transcript: str, image_summary: str | None, image_frame: str | None
) -> None:
    adapter = live_model_adapter_from_settings(Settings())
    candidate = await asyncio.wait_for(
        adapter.detect_candidate(
            LiveObservation(
                transcript=transcript,
                image_summary=image_summary,
                image_frame=image_frame,
            )
        ),
        timeout=30,
    )
    print(candidate.model_dump_json(indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke test the configured live model adapter."
    )
    parser.add_argument(
        "--transcript",
        default="There are trash bags blocking the sidewalk here.",
    )
    parser.add_argument(
        "--image-summary",
        default="Camera points at bagged trash near the curb.",
    )
    parser.add_argument(
        "--image-frame",
        default=None,
        help="Optional image data URL to send with the transcript.",
    )
    args = parser.parse_args()
    asyncio.run(run_smoke(args.transcript, args.image_summary, args.image_frame))


if __name__ == "__main__":
    main()
