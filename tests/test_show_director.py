"""Tests for app/show/director.py — director v2: the modes, the receiver story, the overtone."""

import itertools
import re
from collections import Counter

import pytest

from app.config import ShowConfig
from app.show.director import LISTENS, instruction_for, names_in, plan_round
from app.show.grammar import MOODS
from app.show.script import Line, Round, Run
from app.show.story import Overtone, Story

CAST = ("Daniel", "Moira", "Ralph", "Samantha")
OVERTONES = (
    Overtone(name="up", moods=("happy", "hopeful"), tones={"Warm": ("bright", "cheerful", "radiant")}),
    Overtone(name="level", moods=("calm", "doubtful"), tones={"Plain": ("dry", "terse", "measured")}),
    Overtone(name="down", moods=("sad", "afraid"), tones={"Dark": ("grim", "eerie", "woeful")}),
)
NEIGHBORS = {"up": {"up", "level"}, "level": {"up", "level", "down"}, "down": {"level", "down"}}
KINDS = {"orientation": ("level",), "repair": ("up",), "exchange": ("up", "level"), "re-call": ("level",),
         "breakdown": ("level", "down"), "switch-off": ("level", "down")}
POOLS = {"up": {"Luck": ("Good news.",)}, "level": {"Odd": ("An odd thing.", "Another odd thing.")},
         "down": {"Dark": ("Bad news.", "Worse news.", "The worst news.")}}
AGENDA = ("Find out who the voice is.", "Ask where they are.", "Ask for supplies.", "Ask for a truck.")
STORY = Story(name="lab", title="T", cast=CAST, operator="Samantha", template="",
              events=tuple(e for themes in POOLS.values() for items in themes.values() for e in items),
              tones=tuple(w for o in OVERTONES for words in o.tones.values() for w in words),
              overtones=OVERTONES, kinds=KINDS, weights={"up": 1.0, "level": 2.0, "down": 3.0}, event_pools=POOLS,
              agenda=AGENDA, orientation="Four scientists are trapped in a lab.",
              directions={"repair": "The receiver crackles.", "breakdown": "Smoke pours from the receiver.",
                          "switch-off": "The receiver goes quiet."})
PLAIN = Story(name="lab", title="T", cast=CAST, operator="Samantha", template="",
              events=("First event.", "Second event.", "Third event."), tones=("brittle", "macabre", "woeful"))
SHOW = ShowConfig(interaction_min_s=60, interaction_max_s=180)
QUIET = ShowConfig(interaction_min_s=100000, interaction_max_s=200000)
NUMBERS = {2: "two", 3: "three", 4: "four"}
LISTENER = ("Moira, is it airborne?", None, "I'm Alfredo, in Austin.", None, None, "Hello?", "Ralph, the truck!")


def _show(**knobs):
    return ShowConfig(**{"interaction_min_s": 60, "interaction_max_s": 180, **knobs})


def _quiet(**knobs):
    """Settings under which the receiver never comes back: the show stays in Broadcast."""
    return _show(interaction_min_s=100000, interaction_max_s=200000, **knobs)


def _run(seed=42, moods=True):
    return Run(run_id="r", started="s", story="lab", cast=list(CAST), moods=moods, seed=seed, systems={"": "S"})


def _pins(plan):
    """The speaker pinned to the first or the last line of the plan's grammar, and which: (name, "first"|"last")."""
    rules = plan.grammar.splitlines()
    if "pinned" not in rules[0]:
        return None, None
    return rules[1].split('"')[1], ("first" if rules[0].startswith("root    ::= pinned") else "last")


def _record(run, plan, played_s=0.0, lines=None):
    """Record a planned round; by default its lines follow the grammar — the pinned speaker in place, the others
    in turn, the budget full, the last line a question."""
    if lines is None:
        pinned, where = _pins(plan)
        others = [name for name in plan.speakers if name != pinned] or [pinned]
        names = list(itertools.islice(itertools.cycle(others), plan.max_lines))
        if where == "first":
            names = [pinned] + names[:plan.max_lines - 1]
        elif where == "last":
            names = names[:plan.max_lines - 1] + [pinned]
        lines = [(name, "Line. Over.") for name in names[:-1]] + [(names[-1], "Where are you? Over.")]
    run.rounds.append(Round(n=len(run.rounds) + 1, kind=plan.kind, played_s=played_s, instruction=plan.instruction,
                            listener=plan.listener, speakers=list(plan.speakers), max_lines=plan.max_lines,
                            event=plan.event, tone=plan.tone, overtone=plan.overtone, agenda=plan.agenda,
                            slot=plan.slot, recollects=plan.recollects,
                            lines=[Line(speaker=s, raw=f"{s} (calm): {t}", spoken=t) for s, t in lines]))
    return plan


def _next(run, story=STORY, show=SHOW, played_s=0.0, transcript=None, lines=None):
    """Plan the next round and record it."""
    return _record(run, plan_round(run, story, show, played_s, transcript), played_s, lines)


def _play(run, rounds, step=20.0, heard=LISTENER, story=STORY, show=SHOW):
    """Plan and record rounds, `step` seconds of audio each; after a round the page listens to, the listener says
    the next item of `heard` (None: silence). Returns the plans."""
    replies = itertools.cycle(heard)
    plans = []
    for i in range(rounds):
        listening = bool(run.rounds) and run.rounds[-1].kind in LISTENS
        plans.append(_next(run, story, show, step * i, next(replies) if listening else None))
    return plans


def _in_contact(seed=42, show=SHOW):
    """A run at its first Repair: the sign-on, then the call."""
    run = _run(seed)
    _next(run, show=show)
    assert _next(run, show=show, played_s=200).kind == "repair"
    return run


def _emotions(plan):
    """The moods the plan's grammar allows, in order; None without an emotion rule."""
    rule = next((line for line in plan.grammar.splitlines() if line.startswith("emotion ::=")), None)
    return re.findall(r'"([^"]+)"', rule) if rule else None


def _says_what_the_grammar_enforces(plan):
    rules = plan.grammar.splitlines()
    count = "the next line" if plan.max_lines == 1 else f"the next {NUMBERS[plan.max_lines]} lines"
    assert count in plan.instruction
    pinned, where = _pins(plan)
    if where == "first":
        assert f"{pinned} speaks {'first' if plan.max_lines > 1 else 'next'}" in plan.instruction
    elif where == "last":
        assert f"then {pinned}:" in plan.instruction
        assert rules[0].startswith(f"root    ::= line{{{plan.max_lines - 1},{plan.max_lines - 1}}} pinned")
    else:
        assert rules[0].endswith(f",{plan.max_lines}}}")
        assert all(name in plan.instruction for name in plan.speakers)
    moods = _emotions(plan)
    if moods:
        assert f"one of: {', '.join(moods)}." in plan.instruction


class TestEveryKind:
    def test_every_kind_comes_up_and_its_words_state_its_grammar(self):
        plans = _play(_run(), 200, show=_show(interaction_min_s=20, interaction_max_s=40, orientation_every=15))

        assert {p.kind for p in plans} == {"orientation", "free", "repair", "exchange", "re-call", "breakdown",
                                          "switch-off"}
        assert {p.slot for p in plans} >= {None, "aftermath"}
        for plan in plans:
            _says_what_the_grammar_enforces(plan)

    def test_same_seed_replays_the_same_plans(self):
        assert _play(_run(seed=7), 60) == _play(_run(seed=7), 60)
        assert _play(_run(seed=7), 60) != _play(_run(seed=8), 60)

    def test_moods_off(self):
        for plan in _play(_run(moods=False), 60):
            assert "emotion" not in plan.instruction
            assert "emotion ::=" not in plan.grammar

    def test_the_page_listens_after_the_repair_the_exchange_and_the_re_call(self):
        for plan in _play(_run(), 120):
            assert plan.listens == (plan.kind in ("repair", "exchange", "re-call"))


class TestSignOnAndOrientation:
    def test_the_sign_on_opens_the_run(self):
        plan = plan_round(_run(), STORY, SHOW)

        assert (plan.kind, _pins(plan), plan.max_lines, plan.overtone) == (
            "orientation", ("Samantha", "first"), 2, "level")
        assert plan.instruction.startswith("The broadcast begins. Samantha opens it, telling anyone listening, in "
                                           "their own words: Four scientists are trapped in a lab. Samantha speaks "
                                           "first, then Daniel, Moira or Ralph: the next two lines")

    @pytest.mark.parametrize("every, jitter", [(5, 0), (6, 2)])
    def test_orientations_repeat_every_few_free_rounds_opened_by_the_longest_silent(self, every, jitter):
        firsts = set()
        for seed in range(10):
            run = _run(seed)
            _play(run, 80, show=_quiet(orientation_every=every, orientation_jitter=jitter))
            broadcast = [r for r in run.rounds if r.kind in ("free", "orientation")]
            marks = [i for i, r in enumerate(broadcast) if r.kind == "orientation"]
            assert len(marks) > 5
            assert all(every - jitter <= later - earlier - 1 <= every + jitter
                       for earlier, later in zip(marks, marks[1:]))
            firsts |= {r.lines[0].speaker for r in run.rounds[1:] if r.kind == "orientation"}
        assert len(firsts) > 1

    def test_zero_turns_the_repeats_off(self):
        run = _run()
        _play(run, 60, show=_quiet(orientation_every=0))
        assert [r.n for r in run.rounds if r.kind == "orientation"] == [1]


class TestFree:
    def test_speakers_and_budget_stay_in_bounds(self):
        for plan in _play(_run(), 200, show=QUIET):
            if plan.kind == "free":
                assert 2 <= len(plan.speakers) <= 3
                assert list(plan.speakers) == [name for name in CAST if name in plan.speakers]
                assert 1 <= plan.max_lines <= 4

    def test_the_budget_comes_from_the_settings(self):
        budgets = Counter(p.max_lines for seed in range(20) for p in _play(_run(seed), 30, show=QUIET)
                          if p.kind == "free")
        assert set(budgets) == {1, 2, 3, 4}
        assert budgets[2] + budgets[3] > 2 * (budgets[1] + budgets[4])
        fixed = _quiet(free_lines=[3], free_line_weights=[1])
        assert {p.max_lines for p in _play(_run(), 30, show=fixed) if p.kind == "free"} == {3}

    def test_whoever_has_been_silent_longest_is_always_allowed(self):
        for seed in range(50):
            run = _run(seed)
            _next(run, show=QUIET, lines=[("Samantha", "A."), ("Moira", "B.")])
            _next(run, show=QUIET, lines=[("Samantha", "C."), ("Ralph", "D."), ("Moira", "E.")])
            assert "Daniel" in plan_round(run, STORY, QUIET).speakers

    def test_a_name_in_the_last_round_is_allowed(self):
        for seed in range(50):
            run = _run(seed)
            _next(run, show=QUIET, lines=[("Samantha", "A."), ("Daniel", "B.")])
            _next(run, show=QUIET, lines=[("Ralph", "C."), ("Moira", "Ralph, the doors? Over.")])
            assert {"Samantha", "Ralph"} <= set(plan_round(run, STORY, QUIET).speakers)

    def test_a_speaker_naming_themself_is_not_a_name_in_the_last_round(self):
        allowed = []
        for seed in range(50):
            run = _run(seed)
            _next(run, show=QUIET, lines=[("Samantha", "A."), ("Daniel", "B.")])
            _next(run, show=QUIET, lines=[("Moira", "C."), ("Ralph", "Ralph here. Over.")])
            allowed.append("Ralph" in plan_round(run, STORY, QUIET).speakers)
        assert not all(allowed)

    def test_events_come_from_the_rounds_overtone_without_repeats_until_its_pool_is_used(self):
        for seed in range(20):
            run = _run(seed)
            _play(run, 80, show=QUIET)
            for overtone, themes in POOLS.items():
                pool = [e for items in themes.values() for e in items]
                drawn = [r.event for r in run.rounds if r.event and r.overtone == overtone]
                assert set(drawn) <= set(pool)
                for start in range(0, len(drawn), len(pool)):
                    one_pass = drawn[start:start + len(pool)]
                    assert len(set(one_pass)) == len(one_pass)

    def test_an_overtone_without_events_skips_the_event(self):
        story = Story(**{**STORY.__dict__, "event_pools": {"level": POOLS["level"], "down": POOLS["down"]}})
        for seed in range(20):
            for plan in _play(_run(seed), 60, story=story, show=QUIET):
                assert not (plan.overtone == "up" and plan.event)

    def test_an_event_opens_the_instruction_worded_for_the_broadcast(self):
        plans = _play(_run(), 30, show=QUIET)
        assert any(plan.event for plan in plans)
        for plan in plans:
            reported = f"Something happens that the listeners cannot see: {plan.event} The first to speak tells"
            assert plan.instruction.startswith(reported) == bool(plan.event)

    def test_event_report_off_gives_the_offstage_wording(self):
        for plan in _play(_run(), 30, show=_quiet(event_report=False)):
            assert plan.instruction.startswith(f"Offstage: {plan.event} ") == bool(plan.event)

    def test_a_story_without_overtones_draws_from_every_event_tone_word_and_mood(self):
        plans = _play(_run(), 40, story=PLAIN, show=QUIET)
        assert {p.overtone for p in plans} == {None}
        assert {p.event for p in plans if p.event} <= set(PLAIN.events)
        assert {p.tone for p in plans} <= set(PLAIN.tones)
        assert {tuple(_emotions(p)) for p in plans} == {MOODS}


class TestOvertone:
    def test_each_kind_uses_its_allowed_overtones(self):
        for seed in range(10):
            for plan in _play(_run(seed), 150, show=_show(interaction_min_s=20, interaction_max_s=40)):
                if plan.kind in KINDS:
                    assert plan.overtone in KINDS[plan.kind]

    def test_moods_and_tone_word_come_from_the_rounds_overtone(self):
        by_name = {o.name: o for o in OVERTONES}
        for plan in _play(_run(), 150, show=_show(interaction_min_s=20, interaction_max_s=40)):
            overtone = by_name[plan.overtone]
            assert tuple(_emotions(plan)) == overtone.moods
            assert plan.tone in [w for words in overtone.tones.values() for w in words]

    def test_free_rounds_move_only_to_a_neighbor(self):
        for seed in range(30):
            run = _run(seed)
            _play(run, 150, show=_show(interaction_min_s=20, interaction_max_s=40, overtone_hold=1,
                                       overtone_jitter=0))
            chain = [r for r in run.rounds if r.kind in ("free", "breakdown", "switch-off")]
            for before, after in zip(chain, chain[1:]):
                if after.kind == "free":
                    assert after.overtone in NEIGHBORS[before.overtone]

    def test_the_overtone_changes_only_when_its_hold_ends(self):
        for seed in range(30):
            run = _run(seed)
            _play(run, 60, show=_quiet(overtone_hold=3, overtone_jitter=0))
            chain = [r.overtone for r in run.rounds if r.kind == "free"]
            assert all(i % 3 == 0 for i in range(1, len(chain)) if chain[i] != chain[i - 1])

    def test_free_rounds_carry_on_from_the_breakdowns_overtone(self):
        run = _in_contact()
        _record(run, plan_round(run, STORY, SHOW, 210, "Hello?"), 210)
        run.rounds[-1].kind, run.rounds[-1].overtone = "breakdown", "down"
        assert plan_round(run, STORY, _show(overtone_hold=4, overtone_jitter=0), 220).overtone == "down"


class TestCadence:
    @pytest.mark.parametrize("step", [7.0, 20.0])
    def test_never_before_the_minimum_always_by_the_maximum_after_the_receiver_goes_off(self, step):
        for seed in range(30):
            run = _run(seed)
            _play(run, 120, step=step)
            mark, repairs = 0.0, 0
            for i, r in enumerate(run.rounds):
                if r.kind in ("breakdown", "switch-off") and i + 1 < len(run.rounds):
                    mark = run.rounds[i + 1].played_s
                if r.kind == "repair":
                    repairs += 1
                    assert 60 <= r.played_s - mark < 180 + step
            assert repairs >= 2

    def test_the_repair(self):
        run = _run()
        _next(run)
        plan = plan_round(run, STORY, SHOW, played_s=200)

        assert (plan.kind, plan.max_lines, _pins(plan), plan.overtone) == ("repair", 2, ("Samantha", "last"), "up")
        assert plan.grammar.startswith("root    ::= line{1,1} pinned")
        assert plan.instruction.startswith("The lab has fixed the receiver. The receiver crackles. Daniel, Moira or "
                                           "Ralph tells the listeners it works, then Samantha calls out to anyone "
                                           "listening to answer now.")

    def test_after_a_switch_off_the_receiver_is_switched_back_on(self):
        run = _in_contact()
        _next(run, played_s=210)
        _next(run, played_s=215)
        assert run.rounds[-1].kind == "switch-off"
        _next(run, played_s=220)
        plan = plan_round(run, STORY, SHOW, played_s=500)
        assert plan.kind == "repair"
        assert plan.instruction.startswith("The lab switches the receiver back on.")


class TestContact:
    def test_words_after_the_call_give_an_exchange_opened_by_the_first_agenda_item(self):
        plan = plan_round(_in_contact(), STORY, SHOW, 210, "Hello?")

        assert (plan.kind, plan.listener, plan.agenda, _pins(plan)) == (
            "exchange", "Hello?", AGENDA[0], ("Samantha", "first"))
        assert 2 <= plan.max_lines <= 3
        assert plan.grammar.startswith(f"root    ::= pinned line{{{plan.max_lines - 1},{plan.max_lines - 1}}}")
        assert plan.instruction.startswith(f'A voice on the frequency says: "Hello?" Answer what the voice said, '
                                           f"then: {AGENDA[0]} End with a question to the voice. Samantha speaks "
                                           f"first, then Daniel, Moira or Ralph")

    @pytest.mark.parametrize("words, first", [
        ("Is Ralph there? And Moira?", "Ralph"), ("Moira and Ralph, listen.", "Moira"),
        ("moira, is it airborne?", "Samantha"), ("Is Ralphie there?", "Samantha"),
    ])
    def test_the_first_cast_name_in_the_words_answers_first_else_whoever_asked(self, words, first):
        assert _pins(plan_round(_in_contact(), STORY, SHOW, 210, words))[0] == first

    def test_whoever_asked_last_answers_an_unaddressed_voice(self):
        run = _in_contact()
        _next(run, played_s=210, transcript="Hello?", lines=[("Samantha", "A."), ("Moira", "Who are you? Over.")])
        assert _pins(plan_round(run, STORY, SHOW, 220, "It's me."))[0] == "Moira"

    @pytest.mark.parametrize("exchanges, jitter", [(3, 0), (2, 0), (3, 1)])
    def test_the_breakdown_comes_with_the_nth_answer(self, exchanges, jitter):
        show = _show(contact_exchanges=exchanges, contact_jitter=jitter)
        for seed in range(20):
            run = _in_contact(seed, show)
            kinds = [_next(run, show=show, played_s=210, transcript="Hello?").kind for _ in range(exchanges + jitter)]
            answers = kinds.index("breakdown") + 1
            assert exchanges - jitter <= answers <= exchanges + jitter
            assert set(kinds[:answers - 1]) <= {"exchange"}

    def test_the_breakdown_answers_the_last_words_then_the_receiver_fails(self):
        show = _show(contact_exchanges=2, contact_jitter=0)
        run = _in_contact(show=show)
        _next(run, show=show, played_s=210, transcript="I'm Alfredo.")
        plan = plan_round(run, STORY, show, 220, "Moira, we're coming.")

        assert (plan.kind, plan.listener, _pins(plan)[0], plan.listens) == (
            "breakdown", "Moira, we're coming.", "Moira", False)
        assert plan.overtone in ("level", "down")
        assert plan.instruction.startswith('A voice on the frequency says: "Moira, we\'re coming." Earlier in this '
                                           'contact the voice said: "I\'m Alfredo." Answer what the voice said. Then '
                                           "something happens that the listeners cannot see: Smoke pours from the "
                                           "receiver. The one who notices tells the listeners on air that the lab can "
                                           "no longer hear them")
        assert "End with a question" not in plan.instruction

    def test_each_round_after_a_window_reports_the_answers_so_far_and_the_number_that_ends_the_contact(self):
        show = _show(contact_exchanges=3, contact_jitter=0)
        run = _in_contact(show=show)
        plans = [_next(run, show=show, played_s=210, transcript=t) for t in (None, "One.", None, "Two.", "Three.")]

        assert [(p.kind, p.answers) for p in plans] == [
            ("re-call", (0, 3)), ("exchange", (1, 3)), ("re-call", (1, 3)), ("exchange", (2, 3)),
            ("breakdown", (3, 3))]
        assert plan_round(run, STORY, show, 220).answers is None

    def test_agenda_items_never_repeat_within_a_contact(self):
        show = _show(contact_exchanges=5, contact_jitter=0, interaction_min_s=20, interaction_max_s=40)
        for seed in range(10):
            run = _run(seed)
            _play(run, 120, heard=("Yes.",), show=show)
            contact = []
            for r in run.rounds:
                if r.kind == "repair":
                    assert len(set(contact)) == len(contact)
                    contact = []
                elif r.agenda:
                    contact.append(r.agenda)
                    assert contact[0] == AGENDA[0]

    def test_earlier_contacts_are_restated_up_to_the_setting(self):
        show = _show(contact_exchanges=1, contact_jitter=0, interaction_min_s=20, interaction_max_s=40,
                     restatement_contacts=1)
        run = _run()
        _play(run, 40, heard=("First voice.", "Second voice.", "Third voice."), show=show)
        last = [r for r in run.rounds if r.kind == "breakdown"][-1].instruction
        listed = last.split("oldest first — ")[1].split(" If this voice")[0]
        assert listed.startswith("1: ") and "2: " not in listed
        assert "greet them as a returning friend and use what they told you" in last


class TestSilence:
    def test_silence_after_the_call_gives_the_operators_re_call_then_the_switch_off(self):
        run = _in_contact()
        re_call = _next(run, played_s=210)
        switch_off = plan_round(run, STORY, SHOW, 215)

        assert (re_call.kind, _pins(re_call), re_call.max_lines) == ("re-call", ("Samantha", "first"), 1)
        assert re_call.instruction.startswith("Only static answers. Samantha calls out once more")
        assert (switch_off.kind, _pins(switch_off)[0], switch_off.listens) == ("switch-off", "Samantha", False)
        assert switch_off.instruction.startswith("Nobody answered the call. Samantha tells the listeners the lab is "
                                                 "switching the receiver off, to save power or to spare the fragile "
                                                 "receiver")
        assert "the broadcast goes on" in switch_off.instruction

    def test_silence_inside_a_contact_calls_the_listener_back_with_the_question(self):
        run = _in_contact()
        _next(run, played_s=210, transcript="I'm Alfredo.",
              lines=[("Samantha", "Alfredo! Over."), ("Ralph", "Where are you? Over.")])
        re_call = _next(run, played_s=220)
        switch_off = plan_round(run, STORY, SHOW, 225)

        assert _pins(re_call)[0] == "Ralph"
        assert ('Ralph calls them back, by name if they gave one, and asks again: "Where are you? Over." '
                in re_call.instruction)
        assert 'Earlier in this contact the voice said: "I\'m Alfredo."' in re_call.instruction
        assert (switch_off.kind, _pins(switch_off)[0]) == ("switch-off", "Ralph")
        assert switch_off.instruction.startswith("The voice is gone. Ralph tells the listeners the lab has lost them")

    def test_an_answer_resets_the_count(self):
        run = _in_contact()
        _next(run, played_s=210)
        _next(run, played_s=215, transcript="Sorry, here.")
        assert plan_round(run, STORY, SHOW, 220).kind == "re-call"

    @pytest.mark.parametrize("silences", [1, 3])
    def test_the_setting_counts_the_silences(self, silences):
        show = _show(silences_to_switch_off=silences)
        run = _in_contact(show=show)
        kinds = [_next(run, show=show, played_s=210).kind for _ in range(silences)]
        assert kinds == ["re-call"] * (silences - 1) + ["switch-off"]

    def test_a_transcript_outside_a_listening_window_is_ignored(self):
        run = _run()
        _next(run)
        assert plan_round(run, STORY, SHOW, 10, "Hello?").kind == "free"


class TestAfterAContact:
    def test_the_aftermath_talks_about_what_the_listener_said(self):
        show = _show(contact_exchanges=2, contact_jitter=0)
        run = _in_contact(show=show)
        _next(run, show=show, played_s=210, transcript="I'm Alfredo.")
        _next(run, show=show, played_s=220, transcript="I have a truck.")
        plan = plan_round(run, STORY, show, 230)

        assert (plan.kind, plan.slot, plan.event, plan.recollects) == ("free", "aftermath", None, 2)
        assert plan.instruction.startswith('The voice on the frequency told you: "I\'m Alfredo." / "I have a truck." '
                                           "Talk among yourselves about what it means for you.")
        _record(run, plan, 230)
        assert plan_round(run, STORY, show, 240).slot is None

    def test_no_aftermath_when_nobody_spoke(self):
        run = _in_contact()
        _next(run, played_s=210)
        _next(run, played_s=215)
        assert plan_round(run, STORY, SHOW, 220).slot is None

    def test_the_aftermath_comes_before_a_due_orientation(self):
        show = _show(contact_exchanges=1, contact_jitter=0, orientation_every=1, orientation_jitter=0)
        run = _in_contact(show=show)
        _next(run, show=show, played_s=210, transcript="I'm Alfredo.")
        assert (_next(run, show=show, played_s=220).slot, run.rounds[-1].kind) == ("aftermath", "free")
        assert plan_round(run, STORY, show, 230).kind == "orientation"

    def test_an_aftermath_does_not_reset_the_count_and_a_recollection_never_follows_one(self):
        show = _show(contact_exchanges=1, contact_jitter=0, orientation_every=0, recollection_every=4,
                     recollection_jitter=0)
        run = _in_contact(show=show)
        _next(run, show=show, played_s=210, transcript="First voice.")
        first = [_next(run, show=show, played_s=t).slot for t in (220, 225, 230)]
        assert _next(run, show=show, played_s=500).kind == "repair"
        _next(run, show=show, played_s=510, transcript="Second voice.")
        second = [_next(run, show=show, played_s=t) for t in (520, 525, 530)]

        assert first == ["aftermath", None, None]
        assert [p.slot for p in second] == ["aftermath", None, "recollection"]
        assert second[2].recollects == 2
        assert second[2].instruction.startswith('Earlier, a voice on the frequency told you: "First voice." Talk '
                                                "among yourselves about what they told you, and imagine how they "
                                                "could help you if they call again.")

    def test_recollections_come_every_few_free_rounds_and_alternate_between_callers(self):
        show = _show(contact_exchanges=1, contact_jitter=0, orientation_every=0, recollection_every=4,
                     recollection_jitter=0)
        run = _in_contact(show=show)
        _next(run, show=show, played_s=210, transcript="First voice.")
        _next(run, show=show, played_s=220)
        assert _next(run, show=show, played_s=500).kind == "repair"
        _next(run, show=show, played_s=510, transcript="Second voice.")
        quiet = show.model_copy(update={"interaction_min_s": 100000, "interaction_max_s": 200000})
        for _ in range(30):
            _next(run, show=quiet, played_s=520)

        free = [r for r in run.rounds if r.kind == "free"]
        marks = [i for i, r in enumerate(free) if r.slot == "recollection"]
        assert len(marks) >= 5
        assert all(later - earlier == 4 for earlier, later in zip(marks, marks[1:]))
        recalled = [r.recollects for r in run.rounds if r.slot == "recollection"]
        assert all(a != b for a, b in zip(recalled, recalled[1:]))

    def test_zero_turns_recollections_off(self):
        show = _show(contact_exchanges=1, contact_jitter=0, recollection_every=0)
        run = _in_contact(show=show)
        _next(run, show=show, played_s=210, transcript="A voice.")
        quiet = show.model_copy(update={"interaction_min_s": 100000, "interaction_max_s": 200000})
        for _ in range(40):
            _next(run, show=quiet, played_s=220)
        assert not any(r.slot == "recollection" for r in run.rounds)


class TestPacing:
    @pytest.mark.parametrize("every, jitter", [(2, 1), (3, 0), (1, 0)])
    def test_event_gaps_stay_within_bounds(self, every, jitter):
        show = _quiet(event_every=every, event_jitter=jitter, orientation_every=0)
        for seed in range(30):
            run = _run(seed)
            _play(run, 60, story=PLAIN, show=show)
            flags = [r.event is not None for r in run.rounds if r.kind == "free"]
            marks = [i for i, flag in enumerate(flags) if flag]
            assert flags[0]
            assert all(max(1, every - jitter) <= b - a <= every + jitter for a, b in zip(marks, marks[1:]))

    @pytest.mark.parametrize("hold, jitter", [(3, 1), (2, 0), (1, 0)])
    def test_tone_holds_stay_within_bounds(self, hold, jitter):
        show = _quiet(tone_hold=hold, tone_jitter=jitter, orientation_every=0)
        for seed in range(30):
            run = _run(seed)
            _play(run, 60, story=PLAIN, show=show)
            lengths = [len(list(g)) for _, g in itertools.groupby(r.tone for r in run.rounds if r.tone)]
            assert all(max(1, hold - jitter) <= n <= hold + jitter for n in lengths[:-1])

    def test_a_new_tone_word_differs_from_the_last(self):
        for seed in range(20):
            run = _run(seed)
            _play(run, 40, show=_show(tone_hold=1, tone_jitter=0))
            tones = [r.tone for r in run.rounds if r.tone]
            assert all(a != b for a, b in zip(tones, tones[1:]))

    def test_zero_turns_events_and_tone_words_off(self):
        for plan in _play(_run(), 60, show=_show(event_every=0, tone_hold=0)):
            assert (plan.event, plan.tone) == (None, None)
            assert "Let the tone be" not in plan.instruction


class TestNames:
    @pytest.mark.parametrize("text, names", [
        ("Moira, is it airborne?", {"Moira"}), ("moira?", set()), ("Ralphie", set()),
        ("Daniel and Samantha", {"Daniel", "Samantha"}), ("", set()),
    ])
    def test_whole_words_exact_case(self, text, names):
        assert names_in(text, CAST) == names


class TestWording:
    def test_a_free_round_names_its_speakers_budget_moods_and_tone(self):
        assert instruction_for(("Moira", "Ralph"), 2, None, ("sad", "afraid"), "grim") == (
            "Moira and Ralph speak next: the next two lines, each with the emotion in its voice, one of: sad, "
            "afraid. Let the tone be: grim.")

    def test_the_event_worded_for_the_broadcast(self):
        assert instruction_for(("Moira",), 1, "The lights go out.", ("calm",), report=True) == (
            "Something happens that the listeners cannot see: The lights go out. The first to speak tells the "
            "listeners on air what is happening. Moira speaks next: the next line, with the emotion in its voice, "
            "one of: calm.")

    def test_the_event_offstage_with_moods_off(self):
        assert instruction_for(("Daniel", "Moira", "Ralph"), 4, "Rain.", None) == (
            "Offstage: Rain. Daniel, Moira and Ralph speak next: the next four lines.")
