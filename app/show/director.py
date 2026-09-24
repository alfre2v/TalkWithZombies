"""The director, v0: the smallest one that makes rounds happen.

A pure function of the run's record, the story and the round number.
The random choices come from a generator seeded by the run's seed and
the round number, so a run replays the same plans with nothing extra to
store. Every constraint put in the grammar is also said in the
instruction's words.
"""

import random
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from app.show.grammar import MOODS, build_grammar
from app.show.script import Run
from app.show.story import Story

_NUMBERS = {2: "two", 3: "three", 4: "four"}


@dataclass(frozen=True)
class RoundPlan:
    kind: str
    speakers: Tuple[str, ...]
    max_lines: int
    event: Optional[str]
    instruction: str
    grammar: str


def plan_round(run: Run, story: Story, moods: bool) -> RoundPlan:
    n = len(run.rounds) + 1
    rng = random.Random(f"{run.seed}:{n}")
    chosen = set(rng.sample(list(story.cast), min(rng.choice((2, 3)), len(story.cast))))
    speakers = tuple(name for name in story.cast if name in chosen)
    max_lines = rng.choice((2, 3))
    event = _next_event(run, story, rng) if n % 2 == 1 else None
    return RoundPlan(
        kind="free",
        speakers=speakers,
        max_lines=max_lines,
        event=event,
        instruction=instruction_for(speakers, max_lines, event, moods),
        grammar=build_grammar(speakers, max_lines, MOODS if moods else None),
    )


def _next_event(run: Run, story: Story, rng: random.Random) -> str:
    used = [r.event for r in run.rounds if r.event]
    in_cycle = len(used) % len(story.events)
    recent = set(used[len(used) - in_cycle:]) if in_cycle else set()
    return rng.choice([event for event in story.events if event not in recent])


def _names(speakers: Sequence[str]) -> str:
    if len(speakers) == 1:
        return speakers[0]
    return ", ".join(speakers[:-1]) + " and " + speakers[-1]


def instruction_for(speakers: Sequence[str], max_lines: int, event: Optional[str], moods: bool) -> str:
    verb = "speaks" if len(speakers) == 1 else "speak"
    if max_lines == 1:
        count, tail = "the next line", ", with the emotion in its voice"
    else:
        count, tail = f"the next {_NUMBERS.get(max_lines, str(max_lines))} lines", ", each with the emotion in its voice"
    text = f"{_names(speakers)} {verb} next: {count}{tail if moods else ''}."
    return f"Offstage: {event} {text}" if event else text
