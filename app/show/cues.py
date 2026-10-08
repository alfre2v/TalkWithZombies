"""Sound cues: an event that names a sound plays it.

The story's ``ambience.yaml`` may give a clip ``keywords``: words or phrases that, said by an event, cue that clip.
Only free rounds with an event are cued, and the match happens once, on the server, before the round's first line:
the event's text against the keywords of the ambience's clips that play (enabled by the story and on disk), whole
words, case-insensitive. Several clips may match: one is picked with dice of the round's own, seeded by the run's
seed and the round's number, so a seed replays its cues and never changes the director's draws. The round's stream
then sends ``{"type": "cue", "file", "kind"}`` before its first line, and the page plays it as the first line is
heard: a spot at once, a texture in place of the current one, to its end.
"""

import random
import re
from typing import Optional, Sequence, Tuple

# A clip that may be cued: its file, its kind (texture or spot) and its keywords
CueClip = Tuple[str, str, Tuple[str, ...]]


def cue_dice(seed: int, n: int) -> random.Random:
    """The dice that pick round n's cue: seeded apart from the director's, so a cue never shifts its draws."""
    return random.Random(f"{seed}:{n}:cue")


def says(text: str, keywords: Sequence[str]) -> bool:
    """Whether text says one of the keywords: a whole word or phrase, any case, a phrase's spaces any whitespace."""
    if not keywords:
        return False
    words = "|".join(r"\s+".join(re.escape(part) for part in keyword.split(" ")) for keyword in keywords)
    return re.search(rf"\b(?:{words})\b", text.replace("’", "'"), re.IGNORECASE) is not None


def cue_for(event: Optional[str], clips: Sequence[CueClip], rng: random.Random) -> Optional[Tuple[str, str]]:
    """The clip an event cues, as (file, kind), or None: one of the clips whose keywords the event says, picked
    with rng; the clips in their play order, so the same dice pick the same clip."""
    if not event:
        return None
    matched = [(file, kind) for file, kind, keywords in clips if says(event, keywords)]
    return rng.choice(matched) if matched else None
