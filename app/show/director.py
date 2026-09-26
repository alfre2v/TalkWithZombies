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

Events and tone words are paced in rounds: an event every few free rounds
(the gap), a tone word kept for a few rounds (the hold). Each gap and hold is
drawn once, when it begins, from a generator seeded by the run's seed and that
round, so its length is the same whenever the record is read again.
"""

import itertools
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
        return _answer(story, run.moods, heard) if heard else _static(run, story, show, rng)
    if _time_to_listen(run, show, played_s, rng):
        return _invitation(run, story, show, rng)
    return _free(run, story, show, rng)


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


def _free(run: Run, story: Story, show: ShowConfig, rng: random.Random) -> RoundPlan:
    """Plan a round of the cast talking.
    Two or three names: whoever has been silent longest, anyone named in
    the last round, then random fill. A budget of 1-4 lines weighted to
    2-3, an event when its gap has passed, the tone word of the hold.
    """
    silent = _silent_longest(run, story, rng)
    named = sorted(_named_last_round(run, story) - {silent}, key=story.cast.index)
    size = max(rng.choice((2, 3)), min(3, 1 + len(named)))
    size = min(size, len(story.cast))
    chosen = [silent] + rng.sample(named, min(len(named), size - 1))
    chosen += rng.sample([name for name in story.cast if name not in chosen], size - len(chosen))
    speakers = tuple(name for name in story.cast if name in chosen)
    max_lines = rng.choices(_LINE_BUDGETS, weights=_LINE_WEIGHTS)[0]
    event = _next_event(run, story, rng) if _event_due(run, show) else None
    tone = _tone(run, story, show, rng)
    return _plan("free", speakers, max_lines, run.moods, event=event, tone=tone,
                 instruction=instruction_for(speakers, max_lines, event, run.moods, tone, show.event_report))


def _invitation(run: Run, story: Story, show: ShowConfig, rng: random.Random) -> RoundPlan:
    """Plan the operator's one line asking anyone listening to answer."""
    tone = _tone(run, story, show, rng)
    text = f"{story.operator} turns to the microphone and asks anyone listening to answer: {_count(1, run.moods)}."
    return _plan("invitation", (story.operator,), 1, run.moods, tone=tone, instruction=text + _tone_sentence(tone))


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


def _static(run: Run, story: Story, show: ShowConfig, rng: random.Random) -> RoundPlan:
    """Plan the operator's one line reacting to a listening window that heard nothing."""
    tone = _tone(run, story, show, rng)
    constraint = instruction_for((story.operator,), 1, None, run.moods, tone)
    text = "Only static answers; the broadcast goes on. " + constraint
    return _plan("static", (story.operator,), 1, run.moods, tone=tone, instruction=text)


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


def _event_due(run: Run, show: ShowConfig) -> bool:
    """Decide whether this free round carries an event.

    The run's first free round does. After an event, the next one comes when
    its gap has passed: event_every +/- event_jitter free rounds, drawn once at
    that event. Only free rounds count.
    """
    if show.event_every == 0:
        return False
    last = next((r for r in reversed(run.rounds) if r.event), None)
    if last is None:
        return True
    since = sum(1 for r in run.rounds if r.n > last.n and r.kind == "free") + 1
    return since >= _drawn(run.seed, "gap", last.n, show.event_every, show.event_jitter)


def _next_event(run: Run, story: Story, rng: random.Random) -> str:
    """Draw an event not used since the pool was last used up."""
    return rng.choice(_fresh(story.events, [r.event for r in run.rounds if r.event]))


def _fresh(pool: Sequence[str], used: Sequence[str]) -> list:
    """The items of the pool not used since the pool was last used up (`used`: every draw so far, in order)."""
    in_cycle = len(used) % len(pool)
    recent = set(used[len(used) - in_cycle:]) if in_cycle else set()
    return [item for item in pool if item not in recent]


def _tone(run: Run, story: Story, show: ShowConfig, rng: random.Random) -> Optional[str]:
    """The round's tone word: the current one while its hold lasts, else a new one.

    The hold is tone_hold +/- tone_jitter rounds, drawn once when the word
    began; only the rounds that carry a tone word count. A new word is one not
    used since the list was last used up, and never the word just held. None
    when tone_hold is 0 or the story has no tone words.
    """
    if show.tone_hold == 0 or not story.tones:
        return None
    toned = [r for r in run.rounds if r.tone]
    if not toned:
        return rng.choice(story.tones)
    current = toned[-1].tone
    hold = list(itertools.takewhile(lambda r: r.tone == current, reversed(toned)))
    if len(hold) < _drawn(run.seed, "hold", hold[-1].n, show.tone_hold, show.tone_jitter):
        return current
    words = [word for word, _ in itertools.groupby(r.tone for r in toned)]
    return rng.choice([tone for tone in _fresh(story.tones, words) if tone != current] or list(story.tones))


def _drawn(seed: int, what: str, start: int, mean: int, jitter: int) -> int:
    """The length of the gap or hold that began at round `start`: mean +/- jitter, never below 1."""
    return max(1, mean + random.Random(f"{seed}:{what}:{start}").randint(-jitter, jitter))


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
                    tone: Optional[str] = None, report: bool = False) -> str:
    """Word a round's constraints: the event if any, who speaks next, how many lines, and the tone.

    With report, the event is worded for the broadcast: the listeners cannot
    see it, and the first to speak tells them on air what is happening.
    """
    verb = "speaks" if len(speakers) == 1 else "speak"
    text = f"{_names(speakers)} {verb} next: {_count(max_lines, moods)}.{_tone_sentence(tone)}"
    if not event:
        return text
    if report:
        return (f"Something happens that the listeners cannot see: {event} "
                f"The first to speak tells the listeners on air what is happening. {text}")
    return f"Offstage: {event} {text}"
