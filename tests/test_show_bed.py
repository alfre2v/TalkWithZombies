"""Tests for app/show/bed.py — the static bed's clips, read from Sounds/bed/bed.json.

A usable manifest gives the clips the disk holds, each with its gain; anything else — no manifest, a broken one,
an entry with an unsafe name, a bad gain or no file — gives fewer clips or none, never an error. The story's choice
(its bed.yaml) picks the clips that play and changes their gains by ear. Only a clip the manifest lists and the disk
holds is served. The shipped bed (Sounds/bed/ and the story's bed.yaml, both in the repo) must agree: every clip the
story enables is on disk and in the manifest, every clip is CC0 or CC BY (the app is MIT), and CREDITS.md credits
each one. Which clips the story chooses is not pinned.
"""

import json
import logging

from pathlib import Path

from app.show.bed import bed_clips, bed_play_list, clip_path
from app.show.story import BedClip, _load_bed

REPO = Path(__file__).resolve().parent.parent


def _write(folder, clips, files=None):
    """A manifest listing clips (each a dict as bed.json holds it), and a small file for each name in files."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in files if files is not None else [c["file"] for c in clips]:
        (folder / name).write_bytes(b"ID3")
    (folder / "bed.json").write_text(json.dumps({"loudness_dbfs": -20, "clips": clips}), encoding="utf-8")


class TestBedClips:
    def test_the_clips_of_the_manifest_with_their_gains(self, tmp_path):
        _write(tmp_path, [{"file": "1-hiss.mp3", "gain": 1.5, "seconds": 12.0}, {"file": "2-a.mp3", "gain": 1}])

        assert bed_clips(tmp_path) == [{"file": "1-hiss.mp3", "gain": 1.5}, {"file": "2-a.mp3", "gain": 1.0}]

    def test_no_manifest_no_clips(self, tmp_path):
        assert bed_clips(tmp_path) == []
        assert bed_clips(tmp_path / "missing") == []

    def test_a_broken_manifest_gives_no_clips_and_a_warning(self, tmp_path, caplog):
        (tmp_path / "bed.json").write_text("{not json", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="app.show.bed"):
            assert bed_clips(tmp_path) == []
        assert "cannot be read" in caplog.text

        (tmp_path / "bed.json").write_text(json.dumps({"no": "clips"}), encoding="utf-8")
        assert bed_clips(tmp_path) == []
        (tmp_path / "bed.json").write_text(json.dumps({"clips": "not a list"}), encoding="utf-8")
        assert bed_clips(tmp_path) == []

    def test_unusable_entries_are_skipped_with_a_warning(self, tmp_path, caplog):
        good = {"file": "1-hiss.mp3", "gain": 1.0}
        bad = [
            {"file": "../secret.mp3", "gain": 1.0},
            {"file": ".hidden.mp3", "gain": 1.0},
            {"file": "notes.txt", "gain": 1.0},
            {"file": "2-a.mp3", "gain": -1},
            {"file": "3-b.mp3", "gain": "loud"},
            {"file": "4-c.mp3", "gain": True},
            {"file": "5-missing.mp3", "gain": 1.0},
            {"gain": 1.0},
            "6-plain.mp3",
        ]
        _write(tmp_path, [good, *bad], files=["1-hiss.mp3", "2-a.mp3", "3-b.mp3", "4-c.mp3", "notes.txt"])
        with caplog.at_level(logging.WARNING, logger="app.show.bed"):
            assert bed_clips(tmp_path) == [good]
        assert caplog.text.count("skips an entry") == len(bad)


ON_DISK = [{"file": "1-hiss.mp3", "gain": 2.0}, {"file": "2-crackle.mp3", "gain": 0.5},
           {"file": "3-sweep.mp3", "gain": 1.0}]


class TestPlayList:
    def test_without_the_storys_choice_every_clip_on_disk_plays(self):
        assert bed_play_list(ON_DISK, None) == ON_DISK

    def test_the_storys_enabled_clips_in_its_order_with_its_change_by_ear(self):
        chosen = (BedClip("3-sweep.mp3"), BedClip("2-crackle.mp3", enabled=False),
                  BedClip("1-hiss.mp3", gain_db=-6.0))
        assert bed_play_list(ON_DISK, chosen) == [{"file": "3-sweep.mp3", "gain": 1.0},
                                                  {"file": "1-hiss.mp3", "gain": 1.0024}]

    def test_a_clip_the_story_enables_but_the_disk_lacks_is_skipped_with_a_warning(self, caplog):
        chosen = (BedClip("9-missing.mp3"), BedClip("1-hiss.mp3"))
        with caplog.at_level(logging.WARNING, logger="app.show.bed"):
            assert bed_play_list(ON_DISK, chosen) == [{"file": "1-hiss.mp3", "gain": 2.0}]
        assert "9-missing.mp3" in caplog.text

    def test_nothing_enabled_nothing_plays(self):
        assert bed_play_list(ON_DISK, ()) == []
        assert bed_play_list(ON_DISK, (BedClip("1-hiss.mp3", enabled=False),)) == []


class TestClipPath:
    def test_a_listed_clip_on_disk(self, tmp_path):
        _write(tmp_path, [{"file": "1-hiss.mp3", "gain": 1.0}])
        assert clip_path(tmp_path, "1-hiss.mp3") == tmp_path / "1-hiss.mp3"

    def test_nothing_else(self, tmp_path):
        _write(tmp_path, [{"file": "1-hiss.mp3", "gain": 1.0}], files=["1-hiss.mp3", "2-unlisted.mp3"])
        for name in ("2-unlisted.mp3", "bed.json", "../1-hiss.mp3", "nope.mp3", ""):
            assert clip_path(tmp_path, name) is None, name


class TestShippedBed:
    """The bed that ships with the app: Sounds/bed/ and stories/lab-outbreak/bed.yaml, as committed."""

    FOLDER = REPO / "Sounds" / "bed"

    def _manifest(self):
        return json.loads((self.FOLDER / "bed.json").read_text(encoding="utf-8"))["clips"]

    def test_every_clip_the_story_enables_is_on_disk_and_in_the_manifest(self):
        chosen = _load_bed("lab-outbreak", REPO / "stories" / "lab-outbreak" / "bed.yaml")
        on_disk = bed_clips(self.FOLDER)
        enabled = [c.file for c in chosen if c.enabled]
        assert enabled, "the shipped story enables no clip of the static bed"
        assert [c["file"] for c in bed_play_list(on_disk, chosen)] == enabled

    def test_every_shipped_clip_may_be_redistributed_with_the_app(self):
        clips = self._manifest()
        barred = [c["file"] for c in clips if c["licence_class"] not in ("cc0", "cc-by")]
        assert clips and not barred, f"clips under a licence the app cannot ship (only CC0 and CC BY): {barred}"

    def test_credits_name_every_clip_and_carry_every_required_credit_line(self):
        credits = (self.FOLDER / "CREDITS.md").read_text(encoding="utf-8")
        for clip in self._manifest():
            assert clip["page"] in credits, clip["file"]
            if clip["licence_class"] == "cc-by":
                assert clip["credit"] in credits, clip["file"]
