"""Tests for app/show/cues.py — sound cues: an event that names a sound plays it.

An event says a keyword when the keyword appears as a whole word or phrase, in any case, a phrase's spaces matching
any whitespace and a typographic apostrophe matching a plain one. The cue is one of the clips whose keywords the
event says, picked with the round's own dice: seeded by the run's seed and the round's number, apart from the
director's, so the same seed picks the same clip.
"""

import random

from app.show.cues import cue_dice, cue_for, says

CLIPS = [
    ("explosion-4.mp3", "spot", ("explosion", "explodes")),
    ("explosion-5.mp3", "spot", ("explosion", "explodes")),
    ("thunderstorm-1.mp3", "texture", ("thunder", "lightning strikes")),
    ("dead-crowd-far-1.mp3", "texture", ()),
]


class TestSays:
    def test_a_whole_word_in_any_case(self):
        assert says("An EXPLOSION rattles the windows.", ["explosion"])
        assert says("Something explodes.", ["explosion", "explodes"])

    def test_never_part_of_a_word(self):
        assert not says("Two explosions far away.", ["explosion"])
        assert not says("The thunderous applause.", ["thunder"])

    def test_a_phrase_across_any_whitespace(self):
        assert says("Lightning  strikes the mast.", ["lightning strikes"])
        assert says("Lightning\nstrikes the mast.", ["lightning strikes"])
        assert not says("Lightning flickers; it strikes nothing.", ["lightning strikes"])

    def test_a_typographic_apostrophe_matches_a_plain_one(self):
        assert says("The dead’s howl rises.", ["dead's howl"])

    def test_no_keywords_say_nothing(self):
        assert not says("An explosion.", [])
        assert not says("An explosion.", ())


class TestCueFor:
    def test_no_event_no_cue(self):
        assert cue_for(None, CLIPS, random.Random(1)) is None
        assert cue_for("", CLIPS, random.Random(1)) is None

    def test_an_event_that_says_no_keyword_cues_nothing(self):
        assert cue_for("The moaning outside stops all at once.", CLIPS, random.Random(1)) is None

    def test_the_only_match_with_its_kind(self):
        assert cue_for("Thunder rolls over the lab.", CLIPS, random.Random(1)) == ("thunderstorm-1.mp3", "texture")

    def test_several_matches_one_picked_by_the_dice(self):
        picks = {cue_for("An explosion rattles the windows.", CLIPS, random.Random(seed)) for seed in range(40)}
        assert picks == {("explosion-4.mp3", "spot"), ("explosion-5.mp3", "spot")}

    def test_the_same_dice_pick_the_same_clip(self):
        event = "An explosion rattles the windows."
        assert {cue_for(event, CLIPS, cue_dice(42, 7)) for _ in range(5)} == {cue_for(event, CLIPS, cue_dice(42, 7))}


class TestCueDice:
    def test_seeded_by_the_run_and_the_round(self):
        assert cue_dice(42, 7).random() == cue_dice(42, 7).random()
        assert cue_dice(42, 7).random() != cue_dice(42, 8).random()
        assert cue_dice(42, 8).random() != cue_dice(43, 7).random()

    def test_apart_from_the_directors_dice(self):
        assert cue_dice(42, 7).random() != random.Random("42:7").random()
