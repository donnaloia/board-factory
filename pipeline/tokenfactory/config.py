"""Token Factory pipeline — runtime configuration."""

from __future__ import annotations

import os


def provider_name() -> str:
    return os.environ.get("TOKENFACTORY_PROVIDER", "openai")


#: Number of design reference candidates generated per explore run.
CANDIDATE_COUNT: int = 3

#: Default clip definitions by locomotion profile.
#: Each entry: (clip_name, frame_count, key_frame_indices)
CLIPS_BY_LOCOMOTION: dict[str, list[tuple[str, int, list[int]]]] = {
    "walk": [
        ("idle_breath", 4, [0, 2]),
        # 6 frames, all 3 contact/passing key poses explicitly generated
        ("walk_horizontal", 6, [0, 2, 4]),
    ],
    "float": [
        ("idle_float", 4, [0, 2]),
        ("drift_horizontal", 4, [0, 2]),
    ],
    "fly": [
        ("idle_hover", 4, [0, 2]),
        # 6 frames, all 3 downstroke/mid/upstroke key poses explicitly generated
        ("fly_horizontal", 6, [0, 2, 4]),
    ],
}

#: Cost estimates (USD) per operation — used for the cost-estimator endpoint.
DESIGN_EXPLORE_COST_USD: float = 0.12
GENERATE_CLIP_COST_USD: float = 0.20
PACK_PUBLISH_COST_USD: float = 0.00
