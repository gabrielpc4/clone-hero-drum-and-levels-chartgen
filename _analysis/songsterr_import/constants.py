from __future__ import annotations

from typing import Dict, Tuple

from parse_drums import LANE_BLUE, LANE_GREEN, LANE_KICK, LANE_SNARE, LANE_YELLOW

GM_TO_RB: Dict[int, Tuple[int, bool]] = {
    18: (LANE_GREEN, True),
    35: (LANE_KICK, False),
    36: (LANE_KICK, False),
    37: (LANE_SNARE, False),
    38: (LANE_SNARE, False),
    39: (LANE_SNARE, False),
    40: (LANE_SNARE, False),
    42: (LANE_YELLOW, True),
    44: (LANE_YELLOW, True),
    46: (LANE_BLUE, True),
    49: (LANE_GREEN, True),
    51: (LANE_BLUE, True),
    52: (LANE_GREEN, True),
    53: (LANE_BLUE, True),
    55: (LANE_GREEN, True),
    57: (LANE_GREEN, True),
    59: (LANE_BLUE, True),
}

TOM_PITCHES = (41, 43, 45, 47, 48, 50)
LANE_LETTERS = ["K", "S", "Y", "B", "G"]
