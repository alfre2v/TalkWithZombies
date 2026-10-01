"""The run's record — ``runs/<run-id>/script.json`` — and the messages it becomes.

A run is one performance. Its file is written at the start and rewritten
atomically at the end of each round; bulky data (debug prompts, audio)
lives in separate files beside it. The assembler turns the record back
into what the model reads: the current episode's cast sheet, then the
kept rounds as instruction and reply turns, each reply exactly as the
model wrote it. A fixed line (said word for word, not written by the
model) is never in a reply: it is quoted in the instruction turns, so the
model never reads back a line as its own that it did not write.

The trim keeps the script within the context budget: when the size the
model server last reported reaches show.trim_trigger (90%) of
show.context_budget, whole rounds are flagged `trimmed`, from the middle
outwards, until the script is back to show.trim_target (50%); the first
show.trim_keep_first and the last show.trim_keep_last rounds stay. Each
round records its share of the size (`tokens`) for that count; the next
round's reported size is the truth, so a share a few tokens off never adds
up.
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app import config as app_config
from app.config import ShowConfig
from app.show.story import Story


class Line(BaseModel):
    """A script line; fixed when the director wrote it and a cast member said it word for word."""
    speaker: str
    mood: Optional[str] = None
    raw: str
    spoken: str
    fixed: bool = False


class Heard(BaseModel):
    """What Whisper heard after an invitation.

    `silence` says why it counted as silence; None when it counted as words.
    """
    text: str
    no_speech_prob: Optional[float] = None
    avg_logprob: Optional[float] = None
    silence: Optional[str] = None


class Round(BaseModel):
    """One round of the record.

    The kinds of step 3.4c are "orientation", "free", "repair", "exchange", "re-call", "breakdown" and
    "switch-off"; "invitation", "answer" and "static" come from older records and are kept loadable. overtone is
    the round's overtone, agenda the item an exchange asked, slot what filled a free round's event slot besides
    an event ("aftermath" or "recollection"), recollects the n of the Repair that opened the contact an
    aftermath or a recollection talked about.
    """
    n: int
    kind: Literal["orientation", "free", "repair", "exchange", "last-exchange", "re-call", "breakdown",
                  "switch-off", "invitation", "answer", "static"] = "free"
    played_s: float = 0.0
    instruction: str
    listener: Optional[str] = None
    heard: Optional[Heard] = None
    speakers: List[str]
    max_lines: int
    event: Optional[str] = None
    tone: Optional[str] = None
    lines: List[Line] = Field(default_factory=list)
    dropped: List[str] = Field(default_factory=list)
    timings: Optional[Dict[str, int]] = None
    finish_reason: Optional[str] = None
    trimmed: bool = False
    tokens: Optional[int] = None
    trims: List[int] = Field(default_factory=list)
    episode: str = ""
    overtone: Optional[str] = None
    agenda: Optional[str] = None
    slot: Optional[str] = None
    recollects: Optional[int] = None


class Run(BaseModel):
    run_id: str
    started: str
    story: str
    cast: List[str]
    moods: bool
    seed: int
    systems: Dict[str, str]
    episode: str = ""
    rounds: List[Round] = Field(default_factory=list)


# A run's id: the time it started (see new_run), with a suffix when two runs start in the same second.
RUN_ID = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:-\d+)?")


def runs_root() -> Path:
    return app_config._PROJECT_ROOT / "runs"


def _path(run_id: str) -> Path:
    return runs_root() / run_id / "script.json"


def new_run(story: Story, show: ShowConfig, system: str, seed: int, now: Optional[datetime] = None) -> Run:
    started = now or datetime.now()
    base = started.strftime("%Y-%m-%dT%H-%M-%S")
    run_id, suffix = base, 2
    while (runs_root() / run_id).exists():
        run_id, suffix = f"{base}-{suffix}", suffix + 1
    (runs_root() / run_id).mkdir(parents=True)
    run = Run(run_id=run_id, started=started.isoformat(timespec="seconds"), story=story.name,
              cast=list(story.cast), moods=show.emotion_tags, seed=seed, systems={"": system})
    save_run(run)
    return run


def save_run(run: Run) -> None:
    path = _path(run.run_id)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(run.model_dump_json(indent=1), encoding="utf-8")
    os.replace(tmp, path)


def load_run(run_id: str) -> Run:
    return Run.model_validate_json(_path(run_id).read_text(encoding="utf-8"))


def append_round(run: Run, round_: Round) -> None:
    run.rounds.append(round_)
    save_run(run)


def reply_text(round_: Round) -> str:
    """The model's own reply in a round: the lines it wrote, one per line. The fixed lines are not the model's."""
    return "".join(line.raw + "\n" for line in round_.lines if not line.fixed)


def _size(timings: Optional[Dict[str, int]]) -> Optional[int]:
    """The script's size a response reported: the prompt read (fresh and cached) plus the reply."""
    if not timings:
        return None
    return sum(timings.get(key, 0) for key in ("prompt_n", "cache_n", "predicted_n"))


def script_size(run: Run) -> Optional[int]:
    """The script's size in tokens after the last round, as the model server reported it; None if unknown."""
    return _size(run.rounds[-1].timings) if run.rounds else None


def known_size(run: Run) -> Optional[int]:
    """The script's size as the model server last reported it, stepping back over the rounds it reported none for.

    A round with no model request (the Repair: both its lines are fixed) gets no size from the server. The size
    before the next round is then the last one reported, from before the Repair, so the next round's share takes in
    what the Repair added too (its instruction joins the next round's turn) and no tokens go uncounted. None when no
    round has a size yet, or when a trim fell after the last reported size (the size no longer holds; the trim never
    falls before a round without a model request since 2026-10-01, so only an older record has that).
    """
    for round_ in reversed(run.rounds):
        if round_.timings:
            return _size(round_.timings)
        if round_.trims:
            return None
    return None


def trim(run: Run, show: ShowConfig) -> List[int]:
    """Flag whole rounds `trimmed` when the script reaches show.trim_trigger of show.context_budget; return their
    numbers.

    The candidates are the rounds the model still reads, except the first show.trim_keep_first and the last
    show.trim_keep_last. The middle candidate is flagged, again and again, until the script is back to
    show.trim_target of the budget or no candidate is left; each flagged round takes its recorded share off the size.
    """
    budget = show.context_budget
    size = script_size(run)
    if size is None or size < show.trim_trigger * budget:
        return []
    read = [r for r in run.rounds if r.episode == run.episode and not r.trimmed and r.lines]
    first, last = show.trim_keep_first, show.trim_keep_last
    candidates = read[first:max(first, len(read) - last)]
    flagged = []
    while size > show.trim_target * budget and candidates:
        round_ = candidates.pop(len(candidates) // 2)
        round_.trimmed = True
        size -= round_.tokens or 0
        flagged.append(round_.n)
    return sorted(flagged)


def round_share(size_before: Optional[int], trimmed_tokens: int, timings: Optional[Dict[str, int]]) -> Optional[int]:
    """The tokens a round added to the script: its reported size less the size before it.

    The size before it is the last size the server reported (known_size: for the
    round after a Repair, the size from before the Repair), less the shares of the
    rounds trimmed just before this one. None when either size is unknown.
    """
    after = _size(timings)
    if size_before is None or after is None:
        return None
    return after - (size_before - trimmed_tokens)


def assemble_messages(run: Run, instruction: str) -> List[Dict[str, str]]:
    """The model's messages: the system prompt, then per round kept its instruction as a user turn and the model's
    own lines as an assistant turn, then the new instruction.

    A fixed line never appears as the model's: it is quoted in its round's instruction; a round without a line of
    the model's joins the next user turn, so user and assistant turns still alternate.
    """
    messages = [{"role": "system", "content": run.systems[run.episode]}]
    carried: List[str] = []
    for round_ in run.rounds:
        if round_.trimmed or round_.episode != run.episode or not round_.lines:
            continue
        carried.append(round_.instruction)
        reply = reply_text(round_)
        if not reply:
            continue
        messages.append({"role": "user", "content": _joined(carried)})
        messages.append({"role": "assistant", "content": reply})
        carried = []
    messages.append({"role": "user", "content": _joined(carried + [instruction])})
    return messages


def _joined(texts: List[str]) -> str:
    """User-turn texts joined into one; a text ending on "Then" runs into the next, whose first letter goes lower
    case ("…answer us." Then a voice on the frequency says …")."""
    joined = ""
    for text in texts:
        if joined.endswith(" Then") and text:
            text = text[0].lower() + text[1:]
        joined = f"{joined} {text}" if joined else text
    return joined
