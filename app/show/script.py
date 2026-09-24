"""The run's record — ``runs/<run-id>/script.json`` — and the messages it becomes.

A run is one performance. Its file is written at the start and rewritten
atomically at the end of each round; bulky data (debug prompts, audio)
lives in separate files beside it. The assembler turns the record back
into what the model reads: the current episode's cast sheet, then the
kept rounds as instruction and reply turns, each reply exactly as the
model wrote it.

The trim keeps the script within the context budget: when the size the
model server last reported reaches 90% of show.context_budget, whole rounds
are flagged `trimmed`, from the middle outwards, until the script is back
to 50%. Each round records its share of the size (`tokens`) for that count;
the next round's reported size is the truth, so a share a few tokens off
never adds up.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app import config as app_config
from app.config import ShowConfig
from app.show.story import Story


class Line(BaseModel):
    speaker: str
    mood: Optional[str] = None
    raw: str
    spoken: str


class Round(BaseModel):
    n: int
    kind: Literal["free", "invitation", "answer", "static"] = "free"
    played_s: float = 0.0
    instruction: str
    listener: Optional[str] = None
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
    return "".join(line.raw + "\n" for line in round_.lines)


_KEEP_FIRST = 2
_KEEP_LAST = 4
_TRIGGER = 0.9
_TARGET = 0.5


def _size(timings: Optional[Dict[str, int]]) -> Optional[int]:
    """The script's size a response reported: the prompt read (fresh and cached) plus the reply."""
    if not timings:
        return None
    return sum(timings.get(key, 0) for key in ("prompt_n", "cache_n", "predicted_n"))


def script_size(run: Run) -> Optional[int]:
    """The script's size in tokens after the last round, as the model server reported it; None if unknown."""
    return _size(run.rounds[-1].timings) if run.rounds else None


def trim(run: Run, budget: int) -> List[int]:
    """Flag whole rounds `trimmed` when the script reaches 90% of the budget; return their numbers.

    The candidates are the rounds the model still reads, except the first two
    and the last four. The middle candidate is flagged, again and again, until
    the script is back to 50% of the budget or no candidate is left; each
    flagged round takes its recorded share off the size.
    """
    size = script_size(run)
    if size is None or size < _TRIGGER * budget:
        return []
    read = [r for r in run.rounds if r.episode == run.episode and not r.trimmed and r.lines]
    candidates = read[_KEEP_FIRST:max(_KEEP_FIRST, len(read) - _KEEP_LAST)]
    flagged = []
    while size > _TARGET * budget and candidates:
        round_ = candidates.pop(len(candidates) // 2)
        round_.trimmed = True
        size -= round_.tokens or 0
        flagged.append(round_.n)
    return sorted(flagged)


def round_share(size_before: Optional[int], trimmed_tokens: int, timings: Optional[Dict[str, int]]) -> Optional[int]:
    """The tokens a round added to the script: its reported size less the size before it.

    The size before it is the previous round's reported size, less the shares
    of the rounds trimmed just before this one. None when either size is unknown.
    """
    after = _size(timings)
    if size_before is None or after is None:
        return None
    return after - (size_before - trimmed_tokens)


def assemble_messages(run: Run, instruction: str) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": run.systems[run.episode]}]
    for round_ in run.rounds:
        if round_.trimmed or round_.episode != run.episode or not round_.lines:
            continue
        messages.append({"role": "user", "content": round_.instruction})
        messages.append({"role": "assistant", "content": reply_text(round_)})
    messages.append({"role": "user", "content": instruction})
    return messages
