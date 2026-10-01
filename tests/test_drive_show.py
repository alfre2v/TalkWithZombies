"""Tests for scripts/drive_show.py — the listener's --heard items, the heard lines, and the checkpoint report.

The app is faked at the script's own functions (post, start, play_round);
the report reads a record and debug folder written into tmp_path.
"""

import base64
import io
import json
import wave

import pytest

from scripts import drive_show

RUN = {"run_id": "2026-09-24T20-00-00", "title": "The Lab", "cast": ["Daniel", "Moira", "Ralph", "Samantha"],
       "operator": "Samantha", "seed": 42}


def _response(body):
    return io.BytesIO(json.dumps(body).encode())


class TestListenerSays:
    def test_text_mode_sends_the_words_or_an_empty_transcript(self, monkeypatch):
        monkeypatch.setattr(drive_show, "post", lambda *a, **k: pytest.fail("text mode calls nothing"))

        assert drive_show.listener_says("http://app", RUN, "Moira, is it airborne?", False) == {
            "transcript": "Moira, is it airborne?"}
        assert drive_show.listener_says("http://app", RUN, "-", False) == {"transcript": ""}

    def test_speak_mode_speaks_in_the_operators_voice_then_sends_what_whisper_heard(self, monkeypatch, capsys):
        calls = []

        def fake_post(url, body, timeout=120):
            calls.append((url, body))
            if url.endswith("/api/tts"):
                return _response({"audio_base64": base64.b64encode(b"RIFF-spoken").decode(), "sample_rate": 24000})
            return _response({"text": "Moira is it airborne", "no_speech_prob": 0.01, "avg_logprob": -0.3})

        monkeypatch.setattr(drive_show, "post", fake_post)

        fields = drive_show.listener_says("http://app", RUN, "Moira, is it airborne?", True)

        assert fields == {"transcript": "Moira is it airborne", "no_speech_prob": 0.01, "avg_logprob": -0.3}
        (tts_url, tts_body), (listen_url, listen_body) = calls
        assert (tts_url, tts_body) == ("http://app/api/tts", {"text": "Moira, is it airborne?",
                                                              "persona_name": "Samantha"})
        assert listen_url == "http://app/api/show/listen"
        assert listen_body == {"run_id": RUN["run_id"], "audio_base64": base64.b64encode(b"RIFF-spoken").decode(),
                               "audio_mime_type": "audio/wav"}
        assert 'Whisper heard "Moira is it airborne" (no_speech_prob 0.010, avg_logprob -0.300)' in (
            capsys.readouterr().out)

    def test_speak_mode_sends_two_seconds_of_silence_for_a_silent_window(self, monkeypatch, capsys):
        calls = []

        def fake_post(url, body, timeout=120):
            calls.append((url, body))
            return _response({"text": "", "no_speech_prob": None, "avg_logprob": None})

        monkeypatch.setattr(drive_show, "post", fake_post)

        assert drive_show.listener_says("http://app", RUN, "-", True)["transcript"] == ""
        [(url, body)] = calls
        assert url.endswith("/api/show/listen")
        with wave.open(io.BytesIO(base64.b64decode(body["audio_base64"]))) as audio:
            assert (audio.getframerate(), audio.getnframes()) == (24000, 48000)
        assert 'the listener says nothing (2 s of silence); Whisper heard "" in ' in capsys.readouterr().out


class TestHeardLine:
    @pytest.mark.parametrize("summary, line", [
        ({"kind": "exchange", "heard": {"text": "Moira, is it airborne?", "silence": None}},
         '  listener: "Moira, is it airborne?"'),
        ({"kind": "last-exchange", "heard": {"text": "We're coming.", "silence": None}},
         '  listener: "We\'re coming."'),
        ({"kind": "re-call", "heard": {"text": "Thank you.", "silence": "a known Whisper hallucination"}},
         '  heard: "Thank you." -> silence: a known Whisper hallucination'),
        ({"kind": "switch-off", "heard": None}, "  heard: nothing sent"),
        ({"kind": "free", "heard": None}, None),
    ])
    def test_the_window_as_printed(self, summary, line):
        assert drive_show.heard_line(summary) == line


class TestContactLine:
    @pytest.mark.parametrize("summary, line", [
        ({"overtone": "positive", "agenda": "Find out who the voice is.", "answers": [1, 3]},
         '  overtone positive · asks "Find out who the voice is." · answers 1 of 3'),
        ({"overtone": "negative", "slot": "aftermath"}, "  overtone negative · aftermath"),
        ({"overtone": None}, None),
    ])
    def test_the_contact_as_printed(self, summary, line):
        assert drive_show.contact_line(summary) == line


class TestDrive:
    """--heard items are used one per listening window, in turn; once they run out, nothing is sent."""

    @pytest.fixture
    def drive(self, monkeypatch, tmp_path):
        record = tmp_path / RUN["run_id"] / "script.json"
        record.parent.mkdir()
        record.write_text(json.dumps({"rounds": [{"timings": {"prompt_n": 1, "cache_n": 2, "predicted_n": 3}}]}))
        kinds = ["free", "repair", None, "repair", None, "repair", None, "free"]
        sent = []

        def fake_play_round(base, run_id, played_s, heard=None):
            """Like the app: after a call, words give an exchange, anything else a re-call; the call listens."""
            sent.append((played_s, heard))
            words = (heard or {}).get("transcript")
            kind = kinds[len(sent) - 1] or ("exchange" if words else "re-call")
            window = {"text": words, "silence": None if words else "nothing heard"} if heard else None
            summary = {"n": len(sent), "kind": kind, "speakers": ["Moira"], "trimmed": [], "dropped": [],
                       "heard": window, "listens": kind == "repair"}
            return {"seconds": 1.0, "first": 0.5, "lines": 1, "summary": summary, "error": None}

        monkeypatch.setattr(drive_show, "start", lambda base, story: RUN)
        monkeypatch.setattr(drive_show, "play_round", fake_play_round)

        def run(*argv):
            monkeypatch.setattr("sys.argv", ["drive_show.py", "--runs-dir", str(tmp_path), "--rounds", "8", *argv])
            return drive_show.main(), sent

        return run

    def test_each_listening_window_takes_the_next_item(self, drive, capsys):
        code, sent = drive("--heard", "Moira, is it airborne?", "--heard", "-")

        assert code == 0
        assert [heard for _, heard in sent] == [None, None, {"transcript": "Moira, is it airborne?"}, None,
                                                {"transcript": ""}, None, None, None]
        assert [played for played, _ in sent] == [0, 20, 40, 60, 80, 100, 120, 140]
        out = capsys.readouterr().out
        assert '  listener: "Moira, is it airborne?"' in out
        assert '  heard: "" -> silence: nothing heard' in out
        assert "  heard: nothing sent" in out

    def test_without_heard_nothing_is_ever_sent(self, drive):
        _, sent = drive()

        assert all(heard is None for _, heard in sent)

    def test_unused_items_are_named(self, drive, capsys):
        drive("--heard", "a", "--heard", "b", "--heard", "c", "--heard", "d")

        assert "1 --heard item(s) unused" in capsys.readouterr().out


def _round(n, kind="free", speakers=("Moira", "Ralph"), lines=("Moira",), max_lines=2, trims=(), listener=None,
           heard=None, fixed=(), timings=True):
    """A recorded round; `fixed` are the indexes of the lines said word for word by code (fixed: true)."""
    return {"n": n, "kind": kind, "speakers": list(speakers), "max_lines": max_lines, "trims": list(trims),
            "lines": [{"speaker": s, "raw": "x", "spoken": "x", **({"fixed": True} if i in fixed else {})}
                      for i, s in enumerate(lines)], "dropped": [],
            "listener": listener, "heard": heard,
            "timings": {"prompt_n": 1, "cache_n": 2, "predicted_n": 3} if timings else None}


def _good_rounds():
    rounds = [_round(n) for n in range(1, 13)]
    rounds[7] = _round(8, "repair", ("Moira", "Samantha"), ("Moira", "Samantha"), 2)
    rounds[8] = _round(9, "exchange", ("Moira",), ("Moira",), 1, listener="Moira, is it airborne?",
                       heard={"text": "Moira, is it airborne?", "silence": None})
    rounds[9] = _round(10, "repair", ("Moira", "Samantha"), ("Moira", "Samantha"), 2)
    rounds[10] = _round(11, "re-call", ("Samantha",), ("Samantha",), 1, heard={"text": "", "silence": "nothing heard"})
    rounds[11] = _round(12, trims=(3, 4, 5))
    return rounds


def _write(folder, rounds, debug=True, difference=0, skip=(), unasked=()):
    """The run's record and its debug files; the rounds in `unasked` say the server reported no size."""
    folder.mkdir(parents=True)
    (folder / "script.json").write_text(json.dumps({"rounds": rounds}))
    if not debug:
        return
    (folder / "debug").mkdir()
    for r in rounds:
        if r["n"] in skip:
            continue
        (folder / "debug" / f"r{r['n']:03d}.request.json").write_text("{}")
        check = ("the rendered prompt has 420 tokens; the server reported no size" if r["n"] in unasked else
                 f"the rendered prompt has 420 tokens; the server read {420 - difference} (prompt_n + cache_n); "
                 f"difference {difference}")
        (folder / "debug" / f"r{r['n']:03d}.txt").write_text(f"round {r['n']}\ntoken check: {check}\n")


class TestReport:
    def test_a_drive_that_meets_every_criterion(self, tmp_path, capsys):
        _write(tmp_path / "run", _good_rounds())

        assert drive_show.report(tmp_path, "run", 12) is True
        out = capsys.readouterr().out
        assert out.count("  PASS  ") == 6
        assert 'round 9 heard "Moira, is it airborne?" -> Moira' in out
        assert "round 11 re-call (nothing heard)" in out
        assert "before round 12 (rounds 3, 4, 5)" in out
        assert "debug files for 12 of 12 rounds; token check difference 0 in 12 of them" in out
        assert out.rstrip().endswith("6 of 6 criteria pass")

    @pytest.mark.parametrize("change, asked, failing", [
        (lambda rs: rs, 13, "12 of 13 rounds played and recorded"),
        (lambda rs: rs[3:], 9, "9 of 9 rounds played and recorded (10 needed)"),
        (lambda rs: [_round(1, speakers=("Ralph",), lines=("Moira",))] + rs[1:], 12, "round 1: Moira not allowed"),
        (lambda rs: [_round(1, lines=("Moira", "Ralph", "Moira"))] + rs[1:], 12, "round 1: 3 lines of 2"),
        (lambda rs: [_round(1, lines=())] + rs[1:], 12, "round 1: no line"),
        (lambda rs: rs[:8] + [_round(9)] + rs[9:], 12, "listener's words: none"),
        (lambda rs: rs[:10] + [_round(11)] + rs[11:], 12, "a re-call or the Switch-off: none"),
        (lambda rs: rs[:11] + [_round(12)], 12, "the trim fired: no"),
    ])
    def test_each_criterion_fails_on_its_own(self, tmp_path, capsys, change, asked, failing):
        _write(tmp_path / "run", change(_good_rounds()))

        assert drive_show.report(tmp_path, "run", asked) is False
        out = capsys.readouterr().out
        [fail] = [line for line in out.splitlines() if line.startswith("  FAIL  ")]
        assert failing in fail

    @pytest.mark.parametrize("write, failing", [
        ({"skip": (5,)}, "missing: rounds 5"),
        ({"difference": 3}, "token check difference 0 in 0 of them; not 0 or not available: rounds 1, 2"),
        ({"debug": False}, "debug files for 0 of 12 rounds; token check difference 0 in 0 of them; missing: rounds 1,"),
    ])
    def test_the_debug_files_and_token_check(self, tmp_path, capsys, write, failing):
        _write(tmp_path / "run", _good_rounds(), **write)

        assert drive_show.report(tmp_path, "run", 12) is False
        [fail] = [line for line in capsys.readouterr().out.splitlines() if line.startswith("  FAIL  ")]
        assert failing in fail

    def test_fixed_lines_are_outside_the_directors_limits(self, tmp_path, capsys):
        # A Breakdown: Samantha's fixed line, then the one reaction the model may write, by Daniel, Moira or Ralph
        rounds = _good_rounds()
        rounds[4] = _round(5, "breakdown", ("Daniel", "Moira", "Ralph"), ("Samantha", "Daniel"), 1, fixed=(0,))
        _write(tmp_path / "run", rounds)

        assert drive_show.report(tmp_path, "run", 12) is True
        assert "lines (1 fixed, outside the director's limits), 0 dropped" in capsys.readouterr().out

    @pytest.mark.parametrize("lines, failing", [
        (("Samantha", "Samantha"), "round 5: Samantha not allowed"),
        (("Samantha", "Daniel", "Moira"), "round 5: 2 lines of 1"),
    ])
    def test_a_fixed_line_does_not_excuse_the_models_lines(self, tmp_path, capsys, lines, failing):
        rounds = _good_rounds()
        rounds[4] = _round(5, "breakdown", ("Daniel", "Moira", "Ralph"), lines, 1, fixed=(0,))
        _write(tmp_path / "run", rounds)

        assert drive_show.report(tmp_path, "run", 12) is False
        [fail] = [line for line in capsys.readouterr().out.splitlines() if line.startswith("  FAIL  ")]
        assert failing in fail

    def test_a_round_without_a_model_request_has_no_size_to_check(self, tmp_path, capsys):
        # The Repair: both lines fixed, nothing sent to the model, so the server reported no size
        rounds = _good_rounds()
        rounds[7] = _round(8, "repair", ("Daniel", "Samantha"), ("Daniel", "Samantha"), 0, fixed=(0, 1),
                           timings=False)
        _write(tmp_path / "run", rounds, unasked=(8,))

        assert drive_show.report(tmp_path, "run", 12) is True
        assert ("token check difference 0 in 11 of them, no model request in 1 (all lines fixed)"
                in capsys.readouterr().out)

    def test_no_size_for_a_round_the_model_wrote_is_a_failure(self, tmp_path, capsys):
        _write(tmp_path / "run", _good_rounds(), unasked=(3,))

        assert drive_show.report(tmp_path, "run", 12) is False
        [fail] = [line for line in capsys.readouterr().out.splitlines() if line.startswith("  FAIL  ")]
        assert "not 0 or not available: rounds 3" in fail

    def test_no_debug_folder_asks_whether_the_switch_is_on(self, tmp_path, capsys):
        _write(tmp_path / "run", _good_rounds(), debug=False)

        drive_show.report(tmp_path, "run", 12)

        assert "(is show.debug on?)" in capsys.readouterr().out
