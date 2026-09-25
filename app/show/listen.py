"""The transcript filter: whether what the listener said counts as words or as silence.

After an invitation, what Whisper heard counts as silence when it is empty or a
single character; when Whisper doubts there was speech at all (its highest
no_speech_prob above show.no_speech_max) or doubts its own reading (its average
avg_logprob below show.logprob_min); or when it is one of Whisper's known
hallucinations, the phrases it produces out of silence and noise. A listener who
really says just "Thank you." is lost with them, the price of the rule.
Upstream's STT placeholder is on the list too, so it can never reach the
director. Silence leads to the static round.
"""

import re
from typing import Optional, Tuple

from app.config import ShowConfig

_KNOWN_NOISE = frozenset({
    "thank you",
    "thank you so much",
    "thank you very much",
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "subtitles by the amara org community",
    "you",
    "no response received from stt server",
})


def _normalized(text: str) -> str:
    """Lower case, punctuation turned into spaces, spaces collapsed."""
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def usable(text: str, no_speech_prob: Optional[float], avg_logprob: Optional[float],
           show: ShowConfig) -> Tuple[Optional[str], Optional[str]]:
    """The listener's words, or None and the reason they count as silence; missing numbers skip their check."""
    words = text.strip()
    if len(_normalized(words)) <= 1:
        return None, "nothing heard"
    if no_speech_prob is not None and no_speech_prob > show.no_speech_max:
        return None, f"no speech (no_speech_prob {no_speech_prob:.2f} > {show.no_speech_max})"
    if avg_logprob is not None and avg_logprob < show.logprob_min:
        return None, f"an unsure reading (avg_logprob {avg_logprob:.2f} < {show.logprob_min})"
    if _normalized(words) in _KNOWN_NOISE:
        return None, "a known Whisper hallucination"
    return words, None
