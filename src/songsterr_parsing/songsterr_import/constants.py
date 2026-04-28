from __future__ import annotations

from typing import Dict, Tuple

from parse_drums import LANE_BLUE, LANE_GREEN, LANE_KICK, LANE_SNARE, LANE_YELLOW


DEFAULT_MINIMUM_SNARE_VELOCITY = 75
SNARE_SOURCE_PITCHES = frozenset({37, 38, 39, 40})


def should_keep_source_hit(
    note_value: int,
    velocity_value: int,
    minimum_snare_velocity: int | None = None,
) -> bool:
    if velocity_value <= 0:
        return False

    # Keep every positive-velocity hit unless the caller explicitly
    # asks for a minimum snare velocity threshold.
    if minimum_snare_velocity is None:
        return True

    if note_value not in SNARE_SOURCE_PITCHES:
        return True

    return velocity_value >= minimum_snare_velocity

GM_TO_RB: Dict[int, Tuple[int, bool]] = {
    # Choked crashes / china keep the same lane family as their open versions.
    17: (LANE_GREEN, True),  # High Crash (Choke)
    18: (LANE_GREEN, True),  # Medium Crash (Choke)
    19: (LANE_GREEN, True),  # China (Choke)
    20: (LANE_BLUE, True),   # Ride Cymbal (Choke)

    # Splash and splash choke feel more natural on blue cymbal.
    21: (LANE_BLUE, True),   # Splash (Choke)

    # Kicks.
    35: (LANE_KICK, False),  # Bass Drum 2
    36: (LANE_KICK, False),  # Bass Drum 1

    # Snare family, including sidestick and rimshot.
    37: (LANE_SNARE, False),  # Side Stick Snare
    38: (LANE_SNARE, False),  # Snare
    40: (LANE_SNARE, False),  # Rim Shot Snare / Electric Snare

    # Hi-hat family. Open hat can still be overridden contextually.
    42: (LANE_YELLOW, True),  # Closed Hi Hat
    46: (LANE_BLUE, True),    # Open Hi Hat / Half Hi Hat family

    # Standard cymbals.
    49: (LANE_GREEN, True),  # Crash Cymbal 1
    51: (LANE_BLUE, True),   # Ride Cymbal / Ride Edge
    52: (LANE_GREEN, True),  # China
    53: (LANE_BLUE, True),   # Ride Bell

    # Splash / crash variants.
    55: (LANE_BLUE, True),   # Splash
    56: (LANE_BLUE, True),   # Cowbell / Low Cowbell-style mapping
    57: (LANE_GREEN, True),  # Medium Crash / Crash Cymbal 2
    59: (LANE_BLUE, True),   # Ride Cymbal 2

    # Cowbell family is grouped on blue for easier gameplay.
    67: (LANE_BLUE, True),   # High Cowbell
    68: (LANE_BLUE, True),   # Cowbell
}

# Base tom roles. Some songs can still apply adaptive/contextual overrides.
TOM_TO_LANE: Dict[int, int] = {
    41: LANE_GREEN,   # Very Low Tom / Low Floor Tom
    43: LANE_GREEN,   # Floor Tom
    45: LANE_GREEN,   # Low Tom / High Floor Tom
    47: LANE_BLUE,    # Mid Tom
    48: LANE_YELLOW,  # High Tom
    50: LANE_YELLOW,  # Higher Tom / High Floor Tom variant
}

LOW_TOM_PITCHES = (41, 43, 45)
UPPER_TOM_PITCHES = (47, 48, 50)
TOM_PITCHES = tuple(TOM_TO_LANE.keys())
# GM floor/mid/high toms — when all four appear in a song, apply quartet lane remap (mapping.py).
FULL_GM_TOM_QUARTET_PITCHES = frozenset({43, 45, 47, 48})
LANE_LETTERS = ["K", "S", "Y", "B", "G"]
