"""The director, v1: the kind of each round, who may speak, and when the radio listens.

A pure function of the run's record, the story, the settings, the seconds of
show audio the page has played since the run started, and the listener's
transcript. Everything it remembers — who spoke when, which events were used,
when the radio last listened — is read from the record. The random choices
come from a generator seeded by the run's seed and the round number, so a run
replays the same plans with nothing extra to store. Every constraint put in
the grammar is also said in the instruction's words.

The kinds: "free" (the cast talks), "invitation" (the operator asks anyone
listening to answer; the page listens next), "answer" (after an invitation,
the character the listener addressed answers), "static" (after an invitation
that heard nothing, the operator reacts to the silence).
"""

import random
import re
from dataclasses import dataclass
from typing import Optional, Sequence, Set, Tuple

from app.config import ShowConfig
from app.show.grammar import MOODS, build_grammar
from app.show.script import Run
from app.show.story import Story

_NUMBERS = {2: "two", 3: "three", 4: "four"}
_LINE_BUDGETS = (1, 2, 3, 4)
_LINE_WEIGHTS = (1, 3, 3, 1)


@dataclass(frozen=True)
class RoundPlan:
    """One round's plan: its kind, who may speak, the line budget, and the words and grammar that state them."""
    kind: str
    speakers: Tuple[str, ...]
    max_lines: int
    event: Optional[str]
    tone: Optional[str]
    listener: Optional[str]
    instruction: str
    grammar: str


def plan_round(run: Run, story: Story, show: ShowConfig, played_s: float = 0.0,
               transcript: Optional[str] = None) -> RoundPlan:
    """Plan the run's next round.
    After an invitation, the listener's transcript decides: words give an
    answer round, silence a static one. Otherwise the cadence decides
    between an invitation and a free round.
    """
    n = len(run.rounds) + 1
    rng = random.Random(f"{run.seed}:{n}")
    if run.rounds and run.rounds[-1].kind == "invitation":
        heard = (transcript or "").strip()
        return _answer(story, run.moods, heard) if heard else _static(story, run.moods, rng)
    if _time_to_listen(run, show, played_s, rng):
        return _invitation(story, run.moods, rng)
    return _free(run, story, rng, n)


def _time_to_listen(run: Run, show: ShowConfig, played_s: float, rng: random.Random) -> bool:
    """Decide whether this round invites the listeners.
    Counts the seconds played since the last invitation (or since the
    start): never below interaction_min_s, always at interaction_max_s, a
    chance rising linearly in between.
    """
    marks = [r.played_s for r in run.rounds if r.kind == "invitation"]
    since = played_s - (marks[-1] if marks else 0.0)
    if since >= show.interaction_max_s:
        return True
    if since < show.interaction_min_s:
        return False
    return rng.random() < (since - show.interaction_min_s) / (show.interaction_max_s - show.interaction_min_s)


def _free(run: Run, story: Story, rng: random.Random, n: int) -> RoundPlan:
    """Plan a round of the cast talking.
    Two or three names: whoever has been silent longest, anyone named in
    the last round, then random fill. A budget of 1-4 lines weighted to
    2-3, an event on odd rounds, a tone word.
    """
    silent = _silent_longest(run, story, rng)
    named = sorted(_named_last_round(run, story) - {silent}, key=story.cast.index)
    size = max(rng.choice((2, 3)), min(3, 1 + len(named)))
    size = min(size, len(story.cast))
    chosen = [silent] + rng.sample(named, min(len(named), size - 1))
    chosen += rng.sample([name for name in story.cast if name not in chosen], size - len(chosen))
    speakers = tuple(name for name in story.cast if name in chosen)
    max_lines = rng.choices(_LINE_BUDGETS, weights=_LINE_WEIGHTS)[0]
    event = _next_event(run, story, rng) if n % 2 == 1 else None
    tone = _tone(story, rng)
    return _plan("free", speakers, max_lines, run.moods, event=event, tone=tone,
                 instruction=instruction_for(speakers, max_lines, event, run.moods, tone))


def _invitation(story: Story, moods: bool, rng: random.Random) -> RoundPlan:
    """Plan the operator's one line asking anyone listening to answer."""
    tone = _tone(story, rng)
    text = f"{story.operator} turns to the microphone and asks anyone listening to answer: {_count(1, moods)}."
    return _plan("invitation", (story.operator,), 1, moods, tone=tone, instruction=text + _tone_sentence(tone))


def _answer(story: Story, moods: bool, heard: str) -> RoundPlan:
    """Plan the one-line answer to the listener's words.
    Cast names found in the words narrow who may answer; with none, the
    whole cast may, and the model picks whom the voice addressed.
    """
    addressed = tuple(name for name in story.cast if name in names_in(heard, story.cast))
    if addressed:
        who = f"{_names(addressed, 'or')} answers the voice"
    else:
        who = "The character the voice addressed answers; if it addressed no one, whoever fits best answers"
    text = f'A voice on the frequency says: "{heard}" {who}: {_count(1, moods)}.'
    return _plan("answer", addressed or story.cast, 1, moods, listener=heard, instruction=text)


def _static(story: Story, moods: bool, rng: random.Random) -> RoundPlan:
    """Plan the operator's one line reacting to a listening window that heard nothing."""
    tone = _tone(story, rng)
    text = "Only static answers. " + instruction_for((story.operator,), 1, None, moods, tone)
    return _plan("static", (story.operator,), 1, moods, tone=tone, instruction=text)


def _plan(kind: str, speakers: Sequence[str], max_lines: int, moods: bool, *, instruction: str,
          event: Optional[str] = None, tone: Optional[str] = None, listener: Optional[str] = None) -> RoundPlan:
    """Assemble a plan, building its grammar from the same speakers and budget as its words."""
    return RoundPlan(kind=kind, speakers=tuple(speakers), max_lines=max_lines, event=event, tone=tone,
                     listener=listener, instruction=instruction,
                     grammar=build_grammar(speakers, max_lines, MOODS if moods else None))


def _silent_longest(run: Run, story: Story, rng: random.Random) -> str:
    """Name the cast member whose last line is the oldest.
    Never having spoken counts as oldest; ties are drawn at random.
    """
    last_line = {name: -1 for name in story.cast}
    for i, line in enumerate(line for r in run.rounds for line in r.lines):
        if line.speaker in last_line:
            last_line[line.speaker] = i
    oldest = min(last_line.values())
    return rng.choice([name for name in story.cast if last_line[name] == oldest])


def _named_last_round(run: Run, story: Story) -> Set[str]:
    """The cast names in the last round: in the listener's words, and in each line except its speaker's own."""
    if not run.rounds:
        return set()
    last = run.rounds[-1]
    named = names_in(last.listener or "", story.cast)
    for line in last.lines:
        named |= names_in(line.spoken, story.cast) - {line.speaker}
    return named


def names_in(text: str, cast: Sequence[str]) -> Set[str]:
    """The cast names written in the text: whole words, exact case."""
    return {name for name in cast if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text)}


def _next_event(run: Run, story: Story, rng: random.Random) -> str:
    """Draw an event not used since the pool was last used up."""
    used = [r.event for r in run.rounds if r.event]
    in_cycle = len(used) % len(story.events)
    recent = set(used[len(used) - in_cycle:]) if in_cycle else set()
    return rng.choice([event for event in story.events if event not in recent])


def _tone(story: Story, rng: random.Random) -> Optional[str]:
    """Draw a tone word from the story's list, or none if the story has none."""
    return rng.choice(story.tones) if story.tones else None


def _tone_sentence(tone: Optional[str]) -> str:
    """The tone sentence to append to an instruction, or nothing."""
    return f" Let the tone be: {tone}." if tone else ""


def _names(speakers: Sequence[str], conjunction: str = "and") -> str:
    """Join names in prose: "Moira", "Moira and Ralph", "Daniel, Moira or Ralph"."""
    if len(speakers) == 1:
        return speakers[0]
    return ", ".join(speakers[:-1]) + f" {conjunction} " + speakers[-1]


def _count(max_lines: int, moods: bool) -> str:
    """The line budget in words, "the next line" or "the next two lines", with the emotion clause when moods are on."""
    if max_lines == 1:
        return "the next line" + (", with the emotion in its voice" if moods else "")
    number = _NUMBERS.get(max_lines, str(max_lines))
    return f"the next {number} lines" + (", each with the emotion in its voice" if moods else "")


def instruction_for(speakers: Sequence[str], max_lines: int, event: Optional[str], moods: bool,
                    tone: Optional[str] = None) -> str:
    """Word a round's constraints: the event if any, who speaks next, how many lines, and the tone."""
    verb = "speaks" if len(speakers) == 1 else "speak"
    text = f"{_names(speakers)} {verb} next: {_count(max_lines, moods)}.{_tone_sentence(tone)}"
    return f"Offstage: {event} {text}" if event else text
