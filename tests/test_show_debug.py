"""Tests for app/show/debug.py — the debug switch's two files per round, and the voice's chunks kept.

The model server's two calls (render_prompt, count_tokens) are faked at the
module's import site.
"""

import asyncio
import hashlib
import json
import logging

import pytest

import app.show.debug as debug
from app.services.llm import round_payload
from app.show.script import Heard, runs_root

RUN_ID = "2026-09-24T01-23-45"
MESSAGES = [{"role": "system", "content": "S"}, {"role": "user", "content": "Moira speaks next: the next line."}]
GRAMMAR = 'root    ::= line{1,1}\nspeaker ::= "Moira"\n'
PROMPT = ("<SPECIAL_10>System\nS\n<SPECIAL_11>User\nMoira speaks next: the next line.\n"
          "<SPECIAL_11>Assistant\n<think></think>")
FINAL = {"timings": {"prompt_n": 20, "cache_n": 100, "predicted_n": 9}, "finish_reason": "stop"}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def server(monkeypatch):
    """Fake the two model-server calls; `count` is what /tokenize answers, `fail` makes rendering fail."""
    state = {"count": 120, "fail": None}

    async def render_prompt(messages):
        if state["fail"]:
            raise RuntimeError(state["fail"])
        return PROMPT

    async def count_tokens(text):
        return state["count"]

    monkeypatch.setattr(debug, "render_prompt", render_prompt)
    monkeypatch.setattr(debug, "count_tokens", count_tokens)
    return state


def _write(**changes):
    args = dict(run_id=RUN_ID, n=3, kind="free", messages=MESSAGES, grammar=GRAMMAR, max_tokens=512, seed=45,
                reply="Moira (calm): Fine. Over.  \n", final=FINAL)
    args.update(changes)
    _run(debug.write_round(**args))
    return runs_root() / RUN_ID / "debug"


class TestWriteRound:
    def test_the_request_as_sent_and_a_readable_file(self, server):
        folder = _write()

        request = json.loads((folder / "r003.request.json").read_text(encoding="utf-8"))
        assert request == round_payload(MESSAGES, grammar=GRAMMAR, max_tokens=512, seed=45)
        text = (folder / "r003.txt").read_text(encoding="utf-8")
        assert text.startswith(f"round 3 (free) of run {RUN_ID}\nseed 45 | max_tokens 512 | finish stop | ")
        assert ("token check: the rendered prompt has 120 tokens; the server read 120 "
                "(prompt_n + cache_n); difference 0") in text
        assert f"== grammar ==\n{GRAMMAR.rstrip()}\n" in text
        assert f"== the prompt as the model read it (/apply-template) ==\n{PROMPT}\n" in text
        assert text.endswith("== the reply as it streamed ==\nMoira (calm): Fine. Over.  \n\n")

    def test_a_count_that_differs_from_the_servers_is_logged(self, server, caplog):
        server["count"] = 118
        with caplog.at_level(logging.WARNING):
            folder = _write()

        assert "difference -2" in (folder / "r003.txt").read_text(encoding="utf-8")
        assert "has 118 tokens but the server read 120" in caplog.text

    def test_a_failed_render_is_noted_and_logged_never_raised(self, server, caplog):
        server["fail"] = "the server is busy"
        with caplog.at_level(logging.WARNING):
            folder = _write()

        text = (folder / "r003.txt").read_text(encoding="utf-8")
        assert "token check: not available" in text
        assert "(not available: the server is busy)" in text
        assert "could not be rendered for debug" in caplog.text

    def test_a_failed_round_notes_its_error(self, server):
        text = (_write(final={}, reply="Moira (ca", error="the model went away") / "r003.txt").read_text()

        assert "error: the model went away" in text
        assert "token check: the rendered prompt has 120 tokens; the server reported no size" in text

    def test_what_the_listener_said_and_the_verdict(self, server):
        heard = Heard(text="Thank you.", no_speech_prob=0.1, avg_logprob=-0.2, silence="a known Whisper hallucination")
        text = (_write(kind="static", heard=heard) / "r003.txt").read_text(encoding="utf-8")

        assert ("listener: heard 'Thank you.' | no_speech_prob 0.1 | avg_logprob -0.2 | "
                "silence: a known Whisper hallucination") in text

    def test_a_disk_failure_never_raises(self, server, caplog):
        blocked = runs_root() / RUN_ID
        blocked.parent.mkdir(parents=True, exist_ok=True)
        blocked.write_text("a file where the run folder should be")
        with caplog.at_level(logging.WARNING):
            _write()

        assert "debug files not written" in caplog.text


class TestWriteChunk:
    REPLY = {"audio_base64": "QUJD", "sample_rate": 24000, "seed": 737, "time_used": 1.73}

    def _keep(self, tmp_path, tag, **changes):
        clip = tmp_path / "ref-fear.wav"
        clip.write_bytes(b"RIFF-fear")
        args = dict(persona="Daniel", text="Candles! Over.", language="en", asked="ref-fear.wav",
                    used="ref-fear.wav", clip=clip, transcript="a fearful transcript", seed=737, reply=self.REPLY)
        args.update(changes)
        return debug.write_chunk(tag, **args)

    def _run_folder(self):
        folder = runs_root() / RUN_ID
        folder.mkdir(parents=True)
        return folder

    def test_the_audio_and_what_made_it(self, tmp_path):
        self._run_folder()

        wav = self._keep(tmp_path, f"{RUN_ID}/r009-l2-c1")

        assert wav == runs_root() / RUN_ID / "debug" / "audio" / "r009-l2-c1-Daniel-ref-fear.wav"
        assert wav.read_bytes() == b"ABC"
        kept = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
        assert kept.pop("kept")  # The time it was kept
        assert kept == {
            "tag": f"{RUN_ID}/r009-l2-c1",
            "persona": "Daniel",
            "text": "Candles! Over.",
            "language": "en",
            "reference_asked": "ref-fear.wav",
            "reference_used": "ref-fear.wav",
            "clip": str(tmp_path / "ref-fear.wav"),
            "clip_sha256": hashlib.sha256(b"RIFF-fear").hexdigest(),
            "transcript": "a fearful transcript",
            "seed_asked": 737,
            "reply": {"sample_rate": 24000, "seed": 737, "time_used": 1.73},
        }

    def test_the_clip_used_names_the_file_even_when_another_was_asked_for(self, tmp_path):
        self._run_folder()

        wav = self._keep(tmp_path, f"{RUN_ID}/r010-l1-c2", persona="Ralph Jr.", asked="ref-awe.wav", used="ref.wav")

        assert wav.name == "r010-l1-c2-Ralph_Jr_-ref.wav"

    @pytest.mark.parametrize("tag", ["", "../x", f"{RUN_ID}", f"{RUN_ID}/r9-l2-c1", f"{RUN_ID}/r009-l2",
                                     f"{RUN_ID}/../r009-l2-c1", f"{RUN_ID}/r009-l2-c1/../x", f"x/{RUN_ID}/r009-l2-c1",
                                     f"/{RUN_ID}/r009-l2-c1", "latest/r009-l2-c1", f"{RUN_ID}/r009-l2-c1\n"])
    def test_a_tag_that_is_not_a_run_s_and_a_place_s_keeps_nothing(self, tmp_path, caplog, tag):
        self._run_folder()
        with caplog.at_level(logging.WARNING):
            assert self._keep(tmp_path, tag) is None

        assert [p.name for p in runs_root().rglob("*")] == [RUN_ID]
        assert "is not a run's and a place's" in caplog.text

    def test_a_run_with_no_folder_keeps_nothing(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            assert self._keep(tmp_path, f"{RUN_ID}/r009-l2-c1") is None

        assert not (runs_root() / RUN_ID).exists()
        assert f"no run {RUN_ID}" in caplog.text

    def test_a_failure_never_raises(self, tmp_path, caplog):
        self._run_folder()
        with caplog.at_level(logging.WARNING):
            assert self._keep(tmp_path, f"{RUN_ID}/r009-l2-c1", reply={"audio_base64": "not base64!"}) is None

        assert "chunk 2026-09-24T01-23-45/r009-l2-c1 not kept" in caplog.text
