"""The director, v2 (step 3.4c): the show's two modes, the receiver story, and the emotional overtone.

A pure function of the run's record, the story, the settings, the seconds of show audio the page has played
since the run started, and the listener's words. Everything it remembers — who spoke when, which events and
agenda items were used, when the receiver came back or went off, what each listener said — is read from the
record. The random choices come from generators seeded by the run's seed and the round number, so a run replays
the same plans with nothing extra to store. Every constraint put in the grammar is also said in the
instruction's words.

Broadcast: the lab's receiver is down. The cast talk among themselves in free rounds, whose event slot may hold
an event, an aftermath (the first free round after a contact the listener spoke in: what they said) or a
recollection (every few free rounds: a past caller, and how they could help). An orientation tells newcomers
who the cast are and why the radio only listens sometimes: the sign-on at round 1, then every few free rounds.
When the cadence says so, a Repair brings the receiver back: someone announces it, the operator calls out, and
the page listens.

Contact: a listener answered. Each exchange answers them first — the character they named, else whoever asked
them last — then asks the next agenda item, and the page listens again. The listener's N-th answer gets the
last exchange, which answers without asking, and the page does not listen: the Breakdown follows at once, and
the receiver fails. Silence in any listening window counts: a re-call asks again, and after enough silences in a
row a Switch-off turns the receiver off by choice. Both return the show to Broadcast, and the cadence counts from
the moment the receiver went off.

Each round has an overtone (the story's overtones.yaml). The beats use the overtones the story allows their
kind; free rounds hold one for a stretch, then drift to a neighbor. The grammar's moods, the tone word and the
event all come from the round's overtone, so they never pull against each other.
"""

import itertools
import random
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from app.config import ShowConfig
from app.show.grammar import build_grammar
from app.show.script import Round, Run
from app.show.story import Story, all_moods

_NUMBERS = {2: "two", 3: "three", 4: "four"}

# The page listens after these rounds ("invitation" comes from records made before step 3.4c); the receiver
# is on through these and the last exchange, and goes off with these; free rounds drift on from the overtone of
# these.
LISTENS = frozenset({"repair", "exchange", "re-call", "invitation"})
_ON = LISTENS | {"last-exchange"}
_OPENS = frozenset({"repair", "invitation"})
_OFF = frozenset({"breakdown", "switch-off"})
_DRIFTS = frozenset({"free", "breakdown", "switch-off"})


@dataclass(frozen=True)
class FixedLine:
    """A line the director writes, said word for word by a cast member: the speaker, the mood, the text."""
    speaker: str
    mood: Optional[str]
    text: str


@dataclass(frozen=True)
class RoundPlan:
    """One round's plan: its kind, who may speak, the line budget, and the words and grammar that state them.

    overtone is the round's overtone; agenda the item an exchange asks; slot what fills a free round's event
    slot besides an event ("aftermath" or "recollection"); recollects the Repair that opened the contact an
    aftermath or a recollection talks about; answers, after a listening window, the listener's answers in this
    contact so far and the number that ends it. before holds the fixed lines, said before the model's; max_lines
    counts the model's lines only, and with 0 the model is not asked (grammar is empty).
    """
    kind: str
    speakers: Tuple[str, ...]
    max_lines: int
    event: Optional[str]
    tone: Optional[str]
    listener: Optional[str]
    instruction: str
    grammar: str
    overtone: Optional[str] = None
    agenda: Optional[str] = None
    slot: Optional[str] = None
    recollects: Optional[int] = None
    answers: Optional[Tuple[int, int]] = None
    before: Tuple[FixedLine, ...] = ()

    @property
    def listens(self) -> bool:
        """Whether the page listens after this round."""
        return self.kind in LISTENS

    @property
    def receiver_on(self) -> bool:
        """Whether the receiver still works when this round ends: the rounds that listen, and the last exchange."""
        return self.kind in _ON


def plan_round(run: Run, story: Story, show: ShowConfig, played_s: float = 0.0,
               transcript: Optional[str] = None) -> RoundPlan:
    """Plan the run's next round.

    The sign-on opens the run. After a round the page listened to, the listener's words or silence decide: an
    exchange or the last exchange, a re-call or a Switch-off; after the last exchange, the Breakdown. Otherwise the
    show is in Broadcast: a Repair when the cadence calls, else the aftermath of a contact, an orientation when one
    is due, or a free round.
    """
    n = len(run.rounds) + 1
    rng = random.Random(f"{run.seed}:{n}")
    if not run.rounds:
        return _orientation(run, story, show, rng, sign_on=True)
    if run.rounds[-1].kind in LISTENS:
        return _after_listening(run, story, show, (transcript or "").strip(), rng)
    if run.rounds[-1].kind == "last-exchange":
        return _breakdown(run, story, show, rng)
    if _time_to_listen(run, show, played_s, rng):
        return _repair(run, story, show, rng)
    ended = _aftermath(run)
    if ended:
        return _free(run, story, show, rng, slot="aftermath", words=ended[1], recollects=ended[0])
    if _orientation_due(run, show):
        return _orientation(run, story, show, rng, sign_on=False)
    recalled = _recollection_due(run, show, rng)
    if recalled:
        return _free(run, story, show, rng, slot="recollection", words=recalled[1], recollects=recalled[0])
    return _free(run, story, show, rng)


# --- Broadcast ------------------------------------------------------------------------------------------------

def _time_to_listen(run: Run, show: ShowConfig, played_s: float, rng: random.Random) -> bool:
    """Decide whether this round is a Repair.

    Counts the seconds played since the receiver went off: since the start, or since the round after the last
    Breakdown or Switch-off. Never below interaction_min_s, always at interaction_max_s, a chance rising
    linearly in between.
    """
    off = _last_index(run, _OFF)
    if off is None:
        mark = 0.0
    elif off + 1 < len(run.rounds):
        mark = run.rounds[off + 1].played_s
    else:
        mark = played_s
    since = played_s - mark
    if since >= show.interaction_max_s:
        return True
    if since < show.interaction_min_s:
        return False
    return rng.random() < (since - show.interaction_min_s) / (show.interaction_max_s - show.interaction_min_s)


def _free(run: Run, story: Story, show: ShowConfig, rng: random.Random, *, slot: Optional[str] = None,
          words: Sequence[str] = (), recollects: Optional[int] = None) -> RoundPlan:
    """Plan a round of the cast talking among themselves.

    Two or three names: whoever has been silent longest, anyone named in the last round, then random fill. A
    line budget drawn from the settings, the overtone of the drift, and in the event slot an event when its gap
    has passed — unless the slot holds an aftermath or a recollection, the listener's words. With fixed_lines,
    the first name reads the event word for word as the round's first line, and the model writes the rest of the
    budget, opened by the second name — always at least one line, so a budget of one becomes two: the reading
    and a reaction.
    """
    silent = _silent_longest(run, story, rng)
    named = sorted(_named_last_round(run, story) - {silent}, key=story.cast.index)
    size = max(rng.choice((2, 3)), min(3, 1 + len(named)))
    size = min(size, len(story.cast))
    chosen = [silent] + rng.sample(named, min(len(named), size - 1))
    chosen += rng.sample([name for name in story.cast if name not in chosen], size - len(chosen))
    speakers = tuple(name for name in story.cast if name in chosen)
    max_lines = rng.choices(show.free_lines, weights=show.free_line_weights)[0]
    overtone = _drift(run, story, show)
    event = _next_event(run, story, overtone, rng) if slot is None and _event_due(run, show) else None
    tone = _tone(run, story, show, overtone, rng)
    moods = _moods(run, story, overtone)
    if event and show.fixed_lines:
        reader = chosen[0]
        told = f'Something happens that the listeners cannot see, and {reader} has just told them on air: "{event}"'
        rest = max(max_lines - 1, 1)
        opener = chosen[1] if len(chosen) > 1 else reader
        text = f"{told} Carry on from there. " + _turns(speakers, rest, moods, tone, first=opener)
        return _plan("free", speakers, rest, moods, instruction=text, first=opener, event=event, tone=tone,
                     overtone=overtone, before=(_fixed(reader, moods, event, rng),))
    text = instruction_for(speakers, max_lines, event, moods, tone, show.event_report)
    if slot == "aftermath":
        text = f"{_ended('The voice on the frequency told you: ' + _quoted(words))} Talk among yourselves about " \
               f"what it means for you. {text}"
    elif slot == "recollection":
        text = f"{_ended('Earlier, a voice on the frequency told you: ' + _quoted(words))} Talk among yourselves " \
               f"about what they told you, and imagine how they could help you if they call again. {text}"
    return _plan("free", speakers, max_lines, moods, instruction=text, event=event, tone=tone, overtone=overtone,
                 slot=slot, recollects=recollects)


def _orientation(run: Run, story: Story, show: ShowConfig, rng: random.Random, sign_on: bool) -> RoundPlan:
    """Tell the listeners who the cast are, where they are and the receiver's state, in the speaker's own words.

    The sign-on is the operator's; a repeat is opened by whoever has been silent longest. Up to beat_max_lines
    lines, the first speaker pinned. The receiver is told as dead at the sign-on and after a Breakdown, and as
    switched off after a Switch-off.
    """
    first = story.operator if sign_on else _silent_longest(run, story, rng)
    overtone = _kind_overtone(story, "orientation", rng)
    tone = _tone(run, story, show, overtone, rng)
    moods = _moods(run, story, overtone)
    facts = story.orientation or "who the cast are and where they are."
    off = _last_index(run, _OFF)
    if off is not None and run.rounds[off].kind == "switch-off":
        receiver = "that the lab's receiver is switched off to save it — they can only transmit, and will call out " \
                   "for listeners when it is back on — and"
    else:
        receiver = "that the lab's receiver is dead — they can only transmit, and will call out for listeners when " \
                   "it works — and"
    if sign_on:
        lead = f"The broadcast begins. {first} opens it and tells anyone listening, in their own words, {receiver} " \
               f"who they are and where: {facts}"
    else:
        lead = f"For listeners just tuning in, {first} tells them, in their own words, {receiver} who they are and " \
               f"where: {facts}"
    turns = _turns(story.cast, show.beat_max_lines, moods, tone, first=first)
    return _plan("orientation", story.cast, show.beat_max_lines, moods, instruction=f"{lead} {turns}",
                 first=first, tone=tone, overtone=overtone)


def _orientation_due(run: Run, show: ShowConfig) -> bool:
    """Whether an orientation is due: orientation_every +/- jitter free rounds have passed since the last one."""
    last = next((r for r in reversed(run.rounds) if r.kind == "orientation"), None)
    if show.orientation_every == 0 or last is None:
        return False
    since = sum(1 for r in run.rounds if r.n > last.n and r.kind == "free")
    return since >= _drawn(run.seed, "orientation", last.n, show.orientation_every, show.orientation_jitter)


def _repair(run: Run, story: Story, show: ShowConfig, rng: random.Random) -> RoundPlan:
    """The receiver comes back: someone tells the listeners what happened to it, then the operator tells them the
    lab can hear them and calls for an answer, closing the round; the page listens.

    beat_max_lines lines, the operator's pinned last; with one line, or a cast of one, the operator says it all.
    The wording follows how the receiver went off. With fixed_lines and the story's beats, both lines are fixed —
    the announcement by whoever of the rest has been silent longest, then the operator's call — and the model is
    not asked; the instruction, read back in the next request, tells them as already said, in the words an
    event's reading uses, and ends on "Then", running into what comes next: the voice's answer, or the silence.
    """
    op = story.operator
    others = [name for name in story.cast if name != op]
    overtone = _kind_overtone(story, "repair", rng)
    tone = _tone(run, story, show, overtone, rng)
    moods = _moods(run, story, overtone)
    off = _last_index(run, _OFF)
    switched = off is not None and run.rounds[off].kind == "switch-off"
    back = "switches the receiver, the part of the radio that hears, back on" if switched \
        else "has fixed the receiver, the part of the radio that hears"
    seen = f"Something happens that the listeners cannot see: the lab {back}. " \
           + (f"{story.directions['repair']} " if story.directions.get("repair") else "")
    if show.fixed_lines and story.beats and others:
        pool = story.beats.repair_after_switch_off if switched else story.beats.repair_after_breakdown
        announcement, call = _version(run, pool, rng, first_line=lambda pair: pair[0])
        announcer = _silent_longest(run, story, rng, among=others)
        said = (_fixed(announcer, moods, announcement, rng), _fixed(op, moods, call, rng))
        return _plan("repair", (announcer, op), 0, moods, tone=tone, overtone=overtone, before=said,
                     instruction=f'Something happens that the listeners cannot see, and {announcer} has just told '
                                 f'them on air: "{announcement}" {op} has just called out to anyone listening: '
                                 f'"{call}" Then')
    call = 'in their own words: "We can hear you now. Answer us."'
    lines = show.beat_max_lines
    if not others or lines == 1:
        text = f"{seen}{op} tells the listeners on air what just happened to the receiver, then tells anyone " \
               f"listening, {call} " + _turns((op,), 1, moods, tone)
        return _plan("repair", (op,), 1, moods, instruction=text, tone=tone, overtone=overtone)
    text = f"{seen}First, {_names(others, 'or')} tells the listeners on air, in detail, what just happened to the " \
           f"receiver: what they see and hear. Last, {op} tells anyone listening, {call} " \
           + _turns(story.cast, lines, moods, tone, last=op)
    return _plan("repair", story.cast, lines, moods, instruction=text, min_lines=lines, last=op, tone=tone,
                 overtone=overtone)


# --- Contact --------------------------------------------------------------------------------------------------

def _after_listening(run: Run, story: Story, show: ShowConfig, heard: str, rng: random.Random) -> RoundPlan:
    """The round after a listening window.

    Words: an exchange, or the last exchange once the listener has answered N times in this contact (N drawn
    when the receiver came back); the Breakdown follows it. Silence: a re-call, or the Switch-off after
    silences_to_switch_off in a row.
    """
    period = _receiver_period(run)
    target = _drawn(run.seed, "contact", period[0].n, show.contact_exchanges, show.contact_jitter)
    answered = sum(1 for r in period if r.listener)
    if heard:
        progress = (answered + 1, target)
        if answered + 1 >= target:
            return _last_exchange(run, story, show, heard, rng, progress)
        return _exchange(run, story, show, heard, rng, progress)
    if _silences(period) + 1 >= show.silences_to_switch_off:
        return _switch_off(run, story, show, rng, (answered, target))
    return _re_call(run, story, show, rng, (answered, target))


def _exchange(run: Run, story: Story, show: ShowConfig, heard: str, rng: random.Random,
              answers: Optional[Tuple[int, int]] = None) -> RoundPlan:
    """Answer the listener, then ask the next agenda item; the page listens again.

    contact_min_lines to contact_max_lines lines, drawn; the first pinned to the character the listener named,
    else to whoever asked them last; the rest by the other speakers.
    """
    first = _addressed(run, story, heard)
    lines = rng.randint(show.contact_min_lines, show.contact_max_lines)
    item = _agenda_item(run, story, rng)
    overtone = _kind_overtone(story, "exchange", rng)
    tone = _tone(run, story, show, overtone, rng)
    moods = _moods(run, story, overtone)
    ask = f"Answer what the voice said, then: {item} " if item else "Answer what the voice said. "
    text = f'A voice on the frequency says: "{heard}" {_restatement(run, show)}Speak to the voice directly. ' \
           f"{ask}The last line asks the voice a question. " + _turns(story.cast, lines, moods, tone, first=first)
    return _plan("exchange", story.cast, lines, moods, instruction=text, min_lines=lines, first=first, tone=tone,
                 listener=heard, overtone=overtone, agenda=item, answers=answers)


def _last_exchange(run: Run, story: Story, show: ShowConfig, heard: str, rng: random.Random,
                   answers: Optional[Tuple[int, int]] = None) -> RoundPlan:
    """The listener's last answer in a contact: answered like any exchange — the character they named first, else
    whoever asked them last — but asking nothing, since the page does not listen after it; the Breakdown follows.

    contact_min_lines to contact_max_lines lines, drawn, with the exchange's overtones.
    """
    first = _addressed(run, story, heard)
    lines = rng.randint(show.contact_min_lines, show.contact_max_lines)
    overtone = _kind_overtone(story, "exchange", rng)
    tone = _tone(run, story, show, overtone, rng)
    moods = _moods(run, story, overtone)
    text = f'A voice on the frequency says: "{heard}" {_restatement(run, show)}Speak to the voice directly. ' \
           f"Answer what the voice said. " + _turns(story.cast, lines, moods, tone, first=first)
    return _plan("last-exchange", story.cast, lines, moods, instruction=text, min_lines=lines, first=first,
                 tone=tone, listener=heard, overtone=overtone, answers=answers)


def _breakdown(run: Run, story: Story, show: ShowConfig, rng: random.Random) -> RoundPlan:
    """The receiver fails, right after the last exchange: a receiver beat, like the Switch-off.

    beat_max_lines lines. With fixed_lines and the story's beats, the operator's fixed line opens it, told as an
    event's reading is, and the rest of the cast react; without them, the model writes it all: what happens to the
    receiver, then what it means for the listeners, in the cast's own words.
    """
    overtone = _kind_overtone(story, "breakdown", rng)
    tone = _tone(run, story, show, overtone, rng)
    moods = _moods(run, story, overtone)
    lines = show.beat_max_lines
    if show.fixed_lines and story.beats:
        op = story.operator
        version = _version(run, story.beats.breakdown, rng)
        told = f'Something happens that the listeners cannot see, and {op} has just told them on air: "{version}"'
        others = tuple(name for name in story.cast if name != op)
        rest = lines - 1 if others else 0
        text = f"{told} Carry on from there. " + _turns(others, rest, moods, tone) if rest else told
        return _plan("breakdown", others if rest else (op,), rest, moods, instruction=text, min_lines=rest or 1,
                     tone=tone, overtone=overtone, before=(_fixed(op, moods, version, rng),))
    direction = story.directions.get("breakdown") or "The receiver fails."
    means = 'in their own words: "We can\'t hear you anymore, but we\'re still on the air."'
    if lines >= 2:
        jobs = "The first line tells the listeners on air, in detail, what is happening to the receiver: what they " \
               f"see and hear. The last line tells them, {means}"
    else:
        jobs = f"The line tells the listeners on air what is happening to the receiver, and then, {means}"
    text = f"Something happens that the listeners cannot see: {direction} {jobs} " \
           + _turns(story.cast, lines, moods, tone)
    return _plan("breakdown", story.cast, lines, moods, instruction=text, min_lines=lines, tone=tone,
                 overtone=overtone)


def _re_call(run: Run, story: Story, show: ShowConfig, rng: random.Random,
             answers: Optional[Tuple[int, int]] = None) -> RoundPlan:
    """A listening window came to silence: call once more, and the page listens again.

    Before anyone answered, the operator calls out again; inside a contact, whoever was talking to the listener
    calls them back and repeats the question that went unanswered. One line.
    """
    overtone = _kind_overtone(story, "re-call", rng)
    tone = _tone(run, story, show, overtone, rng)
    moods = _moods(run, story, overtone)
    if not any(r.listener for r in _receiver_period(run)):
        caller = story.operator
        text = f"Only static answers. {caller} calls out once more to anyone listening, asking them to answer now; " \
               f"the receiver is still on. "
    else:
        caller = _asker(run, story)
        question = _last_question(run)
        again = f', and asks again: "{question}"' if question else ""
        text = f"The voice has gone quiet. {_restatement(run, show)}" \
               + _ended(f"{caller} speaks to the voice, calls them by name if they gave one{again}") + " "
    text += _turns(story.cast, 1, moods, tone, first=caller)
    return _plan("re-call", story.cast, 1, moods, instruction=text, first=caller, tone=tone, overtone=overtone,
                 answers=answers)


def _switch_off(run: Run, story: Story, show: ShowConfig, rng: random.Random,
                answers: Optional[Tuple[int, int]] = None) -> RoundPlan:
    """Silences in a row: the lab switches the receiver off by choice; the broadcast goes on.

    beat_max_lines lines, the first pinned to whoever called last: the operator before anyone answered, else
    whoever was talking to the listener. The first line says the receiver is going off and why, the last what it
    means for the listeners; with one line, that line says it all. With fixed_lines and the story's beats, the
    first line is the operator's fixed one, told apart by whether the voice was lost or nobody answered, and the
    rest of the cast react in the lines after it.
    """
    answered = any(r.listener for r in _receiver_period(run))
    caller = _asker(run, story) if answered else story.operator
    overtone = _kind_overtone(story, "switch-off", rng)
    tone = _tone(run, story, show, overtone, rng)
    moods = _moods(run, story, overtone)
    lines = show.beat_max_lines
    opening = "The voice is gone. " if answered else "Nobody answered the call. "
    if show.fixed_lines and story.beats:
        op = story.operator
        pool = story.beats.switch_off_voice_lost if answered else story.beats.switch_off_nobody_answered
        version = _version(run, pool, rng)
        told = f'{opening}{op} has just told the listeners on air: "{version}"'
        others = tuple(name for name in story.cast if name != op)
        rest = lines - 1 if others else 0
        react = "line reacts" if rest == 1 else "lines react"
        text = f"{told} The next {react} to it. " + _turns(others, rest, moods, tone) if rest else told
        return _plan("switch-off", others if rest else (op,), rest, moods, instruction=text, min_lines=rest or 1,
                     tone=tone, overtone=overtone, answers=answers, before=(_fixed(op, moods, version, rng),))
    what = "that the lab has lost them and is switching the receiver off now" if answered \
        else "that the lab is switching the receiver off now"
    says = f"{caller} tells the listeners on air {what}, and why: to save power, or to spare the fragile receiver " \
           f"for a time when someone is more likely to be listening"
    means = 'in their own words: "We won\'t hear you until we switch it back on, but we\'re still on the air."'
    if lines == 1:
        text = f"{opening}{says}; then tells them, {means} "
    else:
        text = f"{opening}First, {says}. The last line tells them, {means} "
    text += _turns(story.cast, lines, moods, tone, first=caller)
    return _plan("switch-off", story.cast, lines, moods, instruction=text, min_lines=lines, first=caller, tone=tone,
                 overtone=overtone, answers=answers)


def _receiver_period(run: Run) -> List[Round]:
    """The rounds since the receiver last came back: from the last Repair (or an old record's invitation) on."""
    start = _last_index(run, _OPENS)
    return run.rounds[start or 0:]


def _silences(period: Sequence[Round]) -> int:
    """How many listening windows in a row, up to the last round, came to silence."""
    return sum(1 for _ in itertools.takewhile(lambda r: not r.listener, reversed(period[1:])))


def _addressed(run: Run, story: Story, heard: str) -> str:
    """Who answers the listener first: the first cast name in their words, else whoever asked them last."""
    found = []
    for name in story.cast:
        match = re.search(rf"(?<!\w){re.escape(name)}(?!\w)", heard)
        if match:
            found.append((match.start(), name))
    return min(found)[1] if found else _asker(run, story)


def _asker(run: Run, story: Story) -> str:
    """Whoever spoke to the listener last: the last line of the last round the page listened to, else the operator."""
    last = next((r for r in reversed(run.rounds) if r.kind in LISTENS), None)
    if last and last.lines and last.lines[-1].speaker in story.cast:
        return last.lines[-1].speaker
    return story.operator


def _last_question(run: Run) -> Optional[str]:
    """What the last round the page listened to ended on: the question that went unanswered."""
    last = next((r for r in reversed(run.rounds) if r.kind in LISTENS and r.lines), None)
    return last.lines[-1].spoken if last else None


def _agenda_item(run: Run, story: Story, rng: random.Random) -> Optional[str]:
    """What the cast ask next: the story's first item opens every contact; then items not asked in this
    contact, and across the run none again until the rest of the list is used up."""
    if not story.agenda:
        return None
    asked = [r.agenda for r in _receiver_period(run) if r.agenda]
    if not asked:
        return story.agenda[0]
    rest = story.agenda[1:]
    used = [r.agenda for r in run.rounds if r.agenda in rest]
    choices = [item for item in _fresh(rest, used) if item not in asked] or [i for i in rest if i not in asked]
    return rng.choice(choices) if choices else None


def _contacts(run: Run) -> List[Tuple[int, List[str]]]:
    """Every contact with words so far, oldest first: the n of the Repair that opened it, and the words."""
    contacts: List[Tuple[int, List[str]]] = []
    for r in run.rounds:
        if r.kind in _OPENS:
            contacts.append((r.n, []))
        elif r.listener and contacts:
            contacts[-1][1].append(r.listener)
    return [(n, words) for n, words in contacts if words]


def _restatement(run: Run, show: ShowConfig) -> str:
    """The listener's words restated next to the question: this contact's so far, then the last few earlier
    contacts', oldest first, with a line to greet a returning voice."""
    opened = _receiver_period(run)[0].n if run.rounds else None
    contacts = _contacts(run)
    now = next((words for n, words in contacts if n == opened), [])
    before = [words for n, words in contacts if n != opened][-show.restatement_contacts:]
    text = _ended(f"Earlier in this contact the voice said: {_quoted(now)}") + " " if now else ""
    if before:
        listed = "; ".join(f"{i}: {_quoted(words)}" for i, words in enumerate(before, 1))
        text += _ended(f"Voices that reached you before, oldest first — {listed}") + " Only a voice that says the " \
                "name of one of them is someone you spoke with before: greet them as a returning friend and use " \
                "what they told you. Any other voice is someone new. "
    return text


# --- After a contact ------------------------------------------------------------------------------------------

def _aftermath(run: Run) -> Optional[Tuple[int, List[str]]]:
    """The contact that just ended — the n of its Repair and the listener's words — if the listener spoke in it
    and no free round has followed it yet; None otherwise."""
    off = _last_index(run, _OFF)
    if off is None or any(r.kind == "free" for r in run.rounds[off + 1:]):
        return None
    start = max((i for i in range(off) if run.rounds[i].kind in _OPENS), default=0)
    words = [r.listener for r in run.rounds[start:off + 1] if r.listener]
    return (run.rounds[start].n, words) if words else None


def _recollection_due(run: Run, show: ShowConfig, rng: random.Random) -> Optional[Tuple[int, List[str]]]:
    """The past contact a free round recalls, when a recollection is due; None otherwise.

    Due recollection_every +/- jitter free rounds after the last recollection (before the first one, after the
    first aftermath); an aftermath does not reset the count, but a recollection never follows one directly. The
    contact is drawn among those not talked about since all of them were — an aftermath counts — and never the
    one talked about last while there is another.
    """
    talked = [r for r in run.rounds if r.slot in ("aftermath", "recollection")]
    anchor = next((r for r in reversed(talked) if r.slot == "recollection"), talked[0] if talked else None)
    if show.recollection_every == 0 or anchor is None or run.rounds[-1].slot == "aftermath":
        return None
    since = sum(1 for r in run.rounds if r.n > anchor.n and r.kind == "free") + 1
    if since < _drawn(run.seed, "recollection", anchor.n, show.recollection_every, show.recollection_jitter):
        return None
    contacts = dict(_contacts(run))
    if not contacts:
        return None
    used = [r.recollects for r in talked if r.recollects in contacts]
    last = used[-1] if used else None
    choices = [n for n in _fresh(list(contacts), used) if n != last] or [n for n in contacts if n != last] \
        or list(contacts)
    chosen = rng.choice(choices)
    return chosen, contacts[chosen]


# --- The overtone ---------------------------------------------------------------------------------------------

def _kind_overtone(story: Story, kind: str, rng: random.Random) -> Optional[str]:
    """One of the overtones the story allows this kind of round; None for a story without overtones."""
    allowed = story.kinds.get(kind)
    return rng.choice(allowed) if allowed else None


def _drift(run: Run, story: Story, show: ShowConfig) -> Optional[str]:
    """A free round's overtone: the current one while its hold lasts, else a draw among it and its neighbors.

    The current overtone is that of the last free round, Breakdown or Switch-off (before the first, the
    sign-on's). Each hold lasts overtone_hold +/- jitter of those rounds, drawn when it began; a draw that stays
    begins a new hold.
    """
    names = [o.name for o in story.overtones]
    if not names:
        return None
    rng = random.Random(f"{run.seed}:drift:{len(run.rounds) + 1}")
    chain = [r for r in run.rounds if r.kind in _DRIFTS and r.overtone in names]
    if not chain:
        start = next((r.overtone for r in run.rounds if r.overtone in names), names[len(names) // 2])
        return _step(names, story.weights, start, rng)
    current = chain[-1].overtone
    p = len(chain) - 1
    while p > 0 and chain[p - 1].overtone == current:
        p -= 1
    while True:
        hold = _drawn(run.seed, "overtone", chain[p].n, show.overtone_hold, show.overtone_jitter)
        if len(chain) < p + hold:
            return current
        if len(chain) == p + hold:
            return _step(names, story.weights, current, rng)
        p += hold


def _step(names: Sequence[str], weights: Dict[str, float], current: str, rng: random.Random) -> str:
    """A draw among the current overtone and its neighbors, with the story's weights."""
    i = names.index(current)
    near = list(names[max(0, i - 1):i + 2])
    shares = [weights.get(name, 0) for name in near]
    return rng.choices(near, weights=shares)[0] if sum(shares) else current


def _moods(run: Run, story: Story, overtone: Optional[str]) -> Optional[Tuple[str, ...]]:
    """The moods a round's lines may carry: its overtone's, or every mood without one; None with moods off."""
    if not run.moods:
        return None
    return next((o.moods for o in story.overtones if o.name == overtone), tuple(all_moods(story)))


def _event_due(run: Run, show: ShowConfig) -> bool:
    """Decide whether this free round carries an event.

    The run's first free round does. After an event, the next one comes when its gap has passed: event_every
    +/- event_jitter free rounds, drawn once at that event. Only free rounds count.
    """
    if show.event_every == 0:
        return False
    last = next((r for r in reversed(run.rounds) if r.event), None)
    if last is None:
        return True
    since = sum(1 for r in run.rounds if r.n > last.n and r.kind == "free") + 1
    return since >= _drawn(run.seed, "gap", last.n, show.event_every, show.event_jitter)


def _next_event(run: Run, story: Story, overtone: Optional[str], rng: random.Random) -> Optional[str]:
    """Draw an event from the round's overtone's pool, not used since that pool was last used up; None when the
    overtone has no events (the event then waits for a later round)."""
    if overtone is None or not story.event_pools:
        pool = story.events
    else:
        pool = tuple(e for items in story.event_pools.get(overtone, {}).values() for e in items)
    if not pool:
        return None
    return rng.choice(_fresh(pool, [r.event for r in run.rounds if r.event in pool]))


def _fresh(pool: Sequence, used: Sequence) -> list:
    """The items of the pool not used since the pool was last used up (`used`: every draw so far, in order)."""
    in_cycle = len(used) % len(pool)
    recent = set(used[len(used) - in_cycle:]) if in_cycle else set()
    return [item for item in pool if item not in recent]


def _tone(run: Run, story: Story, show: ShowConfig, overtone: Optional[str], rng: random.Random) -> Optional[str]:
    """The round's tone word, from its overtone's words: the current word while its hold lasts and it fits,
    else a new one.

    The hold is tone_hold +/- tone_jitter rounds, drawn once when the word began; only the rounds that carry a
    tone word count. A new word is one of the overtone's not used since they were last used up, and never the
    word just held. None when tone_hold is 0 or the overtone has no tone words.
    """
    words = _tone_words(story, overtone)
    if show.tone_hold == 0 or not words:
        return None
    toned = [r for r in run.rounds if r.tone]
    current = toned[-1].tone if toned else None
    if current in words:
        hold = list(itertools.takewhile(lambda r: r.tone == current, reversed(toned)))
        if len(hold) < _drawn(run.seed, "hold", hold[-1].n, show.tone_hold, show.tone_jitter):
            return current
    used = [word for word, _ in itertools.groupby(r.tone for r in toned) if word in words]
    return rng.choice([w for w in _fresh(words, used) if w != current] or [w for w in words if w != current]
                      or list(words))


def _tone_words(story: Story, overtone: Optional[str]) -> Tuple[str, ...]:
    """The tone words of an overtone; every tone word for a story without overtones."""
    for o in story.overtones:
        if o.name == overtone:
            return tuple(w for words in o.tones.values() for w in words)
    return story.tones


# --- Shared ---------------------------------------------------------------------------------------------------

def _plan(kind: str, speakers: Sequence[str], max_lines: int, moods: Optional[Sequence[str]], *, instruction: str,
          min_lines: int = 1, first: Optional[str] = None, last: Optional[str] = None, event: Optional[str] = None,
          tone: Optional[str] = None, listener: Optional[str] = None, overtone: Optional[str] = None,
          agenda: Optional[str] = None, slot: Optional[str] = None, recollects: Optional[int] = None,
          answers: Optional[Tuple[int, int]] = None, before: Sequence[FixedLine] = ()) -> RoundPlan:
    """Assemble a plan, building its grammar from the same speakers, budget, pins and moods as its words; no
    grammar when the model writes no line."""
    grammar = build_grammar(speakers, max_lines, moods, min_lines=min_lines, first=first, last=last) \
        if max_lines else ""
    return RoundPlan(kind=kind, speakers=tuple(speakers), max_lines=max_lines, event=event, tone=tone,
                     listener=listener, instruction=instruction, grammar=grammar,
                     overtone=overtone, agenda=agenda, slot=slot, recollects=recollects, answers=answers,
                     before=tuple(before))


def _fixed(speaker: str, moods: Optional[Sequence[str]], text: str, rng: random.Random) -> FixedLine:
    """A fixed line: the text as a transmission, ending on "Over." like every line, and a mood drawn from the
    round's moods (None with moods off)."""
    return FixedLine(speaker, rng.choice(tuple(moods)) if moods else None, _over(text))


def _over(text: str) -> str:
    """The text ending on "Over.", added unless it already does."""
    text = text.strip()
    return text if text.endswith("Over.") else f"{text} Over."


def _version(run: Run, pool: Sequence, rng: random.Random, first_line=lambda version: version):
    """Draw a version of a fixed line (or of a pair, told apart by its first line): one not said since the pool
    was last used up, read back from the record's fixed lines."""
    def key(text: str) -> str:
        return re.sub(r"[^a-z]", "", text.lower())

    versions = {key(_over(first_line(v))): v for v in pool}
    said = [versions[key(line.spoken)] for r in run.rounds for line in r.lines
            if line.fixed and key(line.spoken) in versions]
    return rng.choice(_fresh(pool, said))


def _last_index(run: Run, kinds: Set[str]) -> Optional[int]:
    """The index of the last round of one of these kinds; None if there is none."""
    return next((i for i in range(len(run.rounds) - 1, -1, -1) if run.rounds[i].kind in kinds), None)


def _quoted(words: Sequence[str]) -> str:
    """The listener's words, each in quotes: "a" / "b"."""
    return " / ".join(f'"{w}"' for w in words)


def _ended(text: str) -> str:
    """The text as a sentence: a period added unless it already ends on one, a quoted one included."""
    return text if text.rstrip('"').endswith((".", "!", "?")) else text + "."


def _silent_longest(run: Run, story: Story, rng: random.Random, among: Optional[Sequence[str]] = None) -> str:
    """Name the cast member (or, with among, the one of those) whose last line is the oldest.
    Never having spoken counts as oldest; ties are drawn at random.
    """
    names = [name for name in story.cast if among is None or name in among]
    last_line = {name: -1 for name in names}
    for i, line in enumerate(line for r in run.rounds for line in r.lines):
        if line.speaker in last_line:
            last_line[line.speaker] = i
    oldest = min(last_line.values())
    return rng.choice([name for name in names if last_line[name] == oldest])


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


def _count(max_lines: int, moods: Optional[Sequence[str]]) -> str:
    """The line budget in words, "the next line" or "the next two lines", with the emotion clause naming the
    allowed moods when moods are on."""
    clause = f"with the emotion in its voice, one of: {', '.join(moods)}" if moods else ""
    if max_lines == 1:
        return "the next line" + (f", {clause}" if clause else "")
    number = _NUMBERS.get(max_lines, str(max_lines))
    return f"the next {number} lines" + (f", each {clause}" if clause else "")


def _turns(speakers: Sequence[str], max_lines: int, moods: Optional[Sequence[str]], tone: Optional[str] = None,
           first: Optional[str] = None, last: Optional[str] = None) -> str:
    """Who speaks, in what order, how many lines, and the tone: the words for what the grammar enforces."""
    others = [name for name in speakers if name not in (first, last)]
    if first is not None and max_lines > 1 and others:
        who = f"{first} speaks first, then {_names(others, 'or')}"
    elif last is not None and others:
        who = f"{_names(others, 'or')} speaks first, then {last}"
    elif first is not None or last is not None:
        who = f"{first or last} speaks next"
    else:
        who = f"{_names(speakers)} {'speaks' if len(speakers) == 1 else 'speak'} next"
    return f"{who}: {_count(max_lines, moods)}.{_tone_sentence(tone)}"


def instruction_for(speakers: Sequence[str], max_lines: int, event: Optional[str],
                    moods: Optional[Sequence[str]], tone: Optional[str] = None, report: bool = False) -> str:
    """Word a free round's constraints: the event if any, who speaks next, how many lines, the moods, the tone.

    With report, the event is worded for the broadcast: the listeners cannot see it, and the first to speak
    tells them on air what is happening.
    """
    text = _turns(speakers, max_lines, moods, tone)
    if not event:
        return text
    if report:
        return (f"Something happens that the listeners cannot see: {event} "
                f"The first to speak tells the listeners on air what is happening. {text}")
    return f"Offstage: {event} {text}"
