"""API tests for app/routers/show.py — POST /api/show/start and /api/show/round.

GET /show is tested for the chooser (no design), the plain page and the designs (?design=<name>): the plain page
must come back unchanged with ?design=plain or an unknown name. The shipped lab-outbreak story is copied into the test's
project root.
The model is faked at the router's import site (app.routers.show.
stream_round) with the real reply recorded on the box on 2026-09-23
(tests/test_show_parser.py), token by token.
"""

import asyncio
import base64
import dataclasses
import json
import logging
import re
import shutil
from pathlib import Path

import pytest
import yaml
from markupsafe import escape

import app.config as app_config
import app.routers.show as show_router
import app.show.debug as show_debug
from app.config import Persona, PersonasConfig, ShowConfig, STTConfig
from app.models import ShowRoundRequest
from app.show.script import Line, Round, append_round, load_run, runs_root, save_run
from tests.factories import make_settings, parse_sse_events, sse_events_by_type
from tests.test_show_parser import REAL_LINES, REAL_ROUND, REAL_TEXT

SHIPPED_STORIES = Path(__file__).resolve().parent.parent / "stories"
CAST = ["Daniel", "Moira", "Ralph", "Samantha"]
FINAL = {"timings": {"prompt_n": 4, "cache_n": 303, "predicted_n": 43}, "finish_reason": "stop"}


@pytest.fixture
def show_env(monkeypatch, tmp_path):
    shutil.copytree(SHIPPED_STORIES, tmp_path / "stories")
    settings = make_settings()
    settings.show = ShowConfig(seed=42)
    monkeypatch.setattr(app_config, "_settings_cache", settings)
    voices = [Persona(name=n, system_prompt="-", reference_audio=f"{n}/ref.wav") for n in CAST]
    monkeypatch.setattr(app_config, "_personas_cache", PersonasConfig(personas=voices))
    return tmp_path


@pytest.fixture
def fake_model(monkeypatch):
    """Replace stream_round with the recorded reply; keep each call's arguments."""
    calls = []

    async def fake_stream_round(messages, *, grammar, max_tokens, seed):
        calls.append({"messages": messages, "grammar": grammar, "max_tokens": max_tokens, "seed": seed})
        for token in REAL_ROUND:
            yield {"token": token}
        yield FINAL

    monkeypatch.setattr(show_router, "stream_round", fake_stream_round)
    return calls


def _start(client):
    resp = client.post("/api/show/start", json={})
    assert resp.status_code == 200
    return resp.json()


def _round(client, run_id, played_s=0, transcript=None, **heard):
    body = {"run_id": run_id, "played_s": played_s, "transcript": transcript, **heard}
    resp = client.post("/api/show/round", json=body)
    assert resp.status_code == 200
    return parse_sse_events(resp.text)


def _summary(events):
    return sse_events_by_type(events, "round")[0]


class TestStart:
    def test_opens_a_run_of_the_configured_story(self, client, show_env):
        body = _start(client)

        assert body["story"] == "lab-outbreak"
        assert body["title"] == "The Lab at the End of the Frequency"
        assert body["cast"] == CAST
        assert (body["operator"], body["seed"]) == ("Samantha", 42)
        run = load_run(body["run_id"])
        assert run.systems[""].startswith("/no_think\nYou write a live radio play.")
        assert run.rounds == []

    def test_gives_the_page_the_listener_timers_and_the_debug_switch(self, client, show_env, monkeypatch):
        body = _start(client)
        assert (body["listen_window_s"], body["press_cap_s"], body["debug"]) == (10.0, 30.0, False)

        monkeypatch.setattr(app_config.get_settings(), "show",
                            ShowConfig(seed=42, listen_window_s=7, press_cap_s=20, debug=True))
        body = _start(client)
        assert (body["listen_window_s"], body["press_cap_s"], body["debug"]) == (7.0, 20.0, True)

    def test_gives_the_page_the_voice_seed_switch(self, client, show_env, monkeypatch):
        assert _start(client)["voice_seed"] is False

        monkeypatch.setattr(app_config.get_settings(), "show", ShowConfig(seed=42, voice_seed=True))
        assert _start(client)["voice_seed"] is True

    def test_gives_the_page_the_voice_of_each_mood_unless_the_switch_is_off(self, client, show_env, monkeypatch):
        # The run's copy of the story gets a made-up mapping, so the test does not depend on the shipped one.
        path = show_env / "stories" / "lab-outbreak" / "overtones.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        moods = [m for spec in data["overtones"].values() for m in spec["moods"]]
        mapping = {m: ("ref-mocked.wav" if i % 2 else "ref.wav") for i, m in enumerate(moods)}
        for spec in data["overtones"].values():
            spec["voices"] = {m: mapping[m] for m in spec["moods"]}
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

        assert _start(client)["voices"] == mapping

        monkeypatch.setattr(app_config.get_settings(), "show", ShowConfig(seed=42, mood_voices=False))
        assert _start(client)["voices"] == {}

    def test_unknown_story_is_refused(self, client, show_env):
        resp = client.post("/api/show/start", json={"story": "nope"})
        assert resp.status_code == 422

    def test_a_missing_voice_is_refused_and_named(self, client, show_env, monkeypatch):
        voices = [Persona(name=n, system_prompt="-", reference_audio="x") for n in CAST[:3]]
        monkeypatch.setattr(app_config, "_personas_cache", PersonasConfig(personas=voices))

        resp = client.post("/api/show/start", json={})

        assert resp.status_code == 422
        assert "Samantha" in resp.json()["detail"]


class TestPage:
    def test_serves_the_show_page_with_its_own_files(self, client):
        resp = client.get("/show?design=plain")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        for asset in ("/static/show/show.css", "/static/show/sse.js", "/static/show/show.js"):
            assert asset in resp.text
        assert "/static/chat.js" not in resp.text

    def test_the_page_files_are_served(self, client):
        for asset in ("/static/show/show.css", "/static/show/sse.js", "/static/show/show.js"):
            assert client.get(asset).status_code == 200


REPO = Path(__file__).resolve().parent.parent
DESIGNS = sorted(p.name for p in (REPO / "static" / "show" / "designs").iterdir() if (p / "design.css").is_file())


def _plain_page():
    """templates/show.html as served: Jinja drops the file's final newline."""
    return (REPO / "templates" / "show.html").read_text(encoding="utf-8").rstrip("\n")


class TestDesigns:
    def test_there_are_designs_to_test(self):
        assert DESIGNS == ["amateur-radio-transmitter", "old-radio"]

    def test_plain_serves_the_plain_page_unchanged(self, client):
        assert client.get("/show?design=plain").text.rstrip("\n") == _plain_page()

    @pytest.mark.parametrize("name", ["nope", "../templates", "..%2Ftemplates", "Old-Radio", "old_radio", "-", ""])
    def test_an_unknown_or_unsafe_design_serves_the_plain_page(self, client, name):
        resp = client.get(f"/show?design={name}")

        assert resp.status_code == 200
        assert resp.text.rstrip("\n") == _plain_page()

    @pytest.mark.parametrize("name", DESIGNS)
    def test_a_design_is_served_with_its_files_over_the_page(self, client, name):
        resp = client.get(f"/show?design={name}")

        assert resp.status_code == 200
        for asset in ("/static/show/show.css", "/static/show/show.js", "/static/show/gauge.js",
                      f"/static/show/designs/{name}/design.css", f"/static/show/designs/{name}/design.js"):
            assert asset in resp.text
            assert client.get(asset).status_code == 200
        assert f'class="design design-{name}"' in resp.text
        assert "/static/show/designs/mock.js" not in resp.text

    def test_mock_fills_a_design_with_a_recorded_stretch(self, client):
        resp = client.get("/show?design=old-radio&mock=1")

        assert "/static/show/designs/mock.js" in resp.text
        assert client.get("/static/show/designs/mock.js").status_code == 200

    def test_without_a_design_the_chooser_offers_every_design_then_the_plain_page(self, client, show_env):
        resp = client.get("/show")

        assert resp.status_code == 200
        assert "/static/show/choose.css" in resp.text
        assert "The Lab at the End of the Frequency" in resp.text
        links = re.findall(r'<a class="card" href="/show\?design=([^"]+)"', resp.text)
        assert links == ["old-radio", "amateur-radio-transmitter", "plain"]
        for name in [*DESIGNS, "plain"]:
            assert f'src="/show?design={name}&amp;mock=1"' in resp.text
        assert client.get("/static/show/choose.css").status_code == 200

    def test_the_chooser_links_to_the_talkwithme_interface(self, client):
        text = client.get("/show").text
        assert '<a href="/talkwithme">Or visit the old TalkWithMe interface that this project is built' in text

    def test_the_plain_mock_is_the_plain_look_filled_with_a_recorded_stretch(self, client):
        resp = client.get("/show?design=plain&mock=1")

        assert resp.status_code == 200
        for asset in ("/static/show/show.css", "/static/show/show.js", "/static/show/designs/mock.js"):
            assert asset in resp.text
        assert "/designs/plain/" not in resp.text
        assert "design.css" not in resp.text
        assert "/static/show/gauge.js" not in resp.text

    def test_the_chooser_takes_each_designs_title_and_line_from_its_folder(self, client):
        text = client.get("/show").text
        for name in DESIGNS:
            about = yaml.safe_load((REPO / "static" / "show" / "designs" / name / "design.yaml").read_text())
            assert str(escape(about["title"])) in text
            assert str(escape(about["about"])) in text

    def test_the_design_template_keeps_every_element_of_the_plain_page(self):
        def ids(name):
            return re.findall(r'\bid="([^"]+)"', (REPO / "templates" / name).read_text(encoding="utf-8"))

        assert ids("show_design.html") == ids("show.html")

    def test_old_radio_serves_its_photograph_and_credits_it(self, client):
        assert client.get("/static/show/designs/old-radio/radio.jpg").status_code == 200
        credits = (REPO / "static" / "show" / "designs" / "old-radio" / "CREDITS.md").read_text(encoding="utf-8")
        assert "Bin im Garten" in credits and "CC BY-SA 3.0" in credits


class TestRound:
    def test_streams_the_chats_events_with_clean_text_and_message_ids(self, client, show_env, fake_model):
        run_id = _start(client)["run_id"]
        events = _round(client, run_id)

        kinds = [e["type"] for e in events if e["type"] != "token"]
        assert kinds == ["start", "done", "start", "done", "round", "complete"]
        starts, dones = sse_events_by_type(events, "start"), sse_events_by_type(events, "done")
        assert [(s["persona"], s["mood"]) for s in starts] == [("Ralph", "urgent"), ("Moira", "afraid")]
        assert [d["text"] for d in dones] == [line.spoken for line in REAL_LINES]
        assert [d["message_id"] for d in dones] == [f"{run_id}-r001-l1", f"{run_id}-r001-l2"]
        assert [s["message_id"] for s in starts] == [d["message_id"] for d in dones]
        tokens = "".join(e["token"] for e in sse_events_by_type(events, "token"))
        assert "’" not in tokens

    def test_records_the_round_with_raw_lines_and_timings(self, client, show_env, fake_model):
        run_id = _start(client)["run_id"]
        summary = sse_events_by_type(_round(client, run_id), "round")[0]

        recorded = load_run(run_id).rounds[0]
        assert recorded.n == 1
        assert [line.raw for line in recorded.lines] == [line.raw for line in REAL_LINES]
        assert recorded.timings == FINAL["timings"]
        assert recorded.finish_reason == "stop"
        assert recorded.speakers == summary["speakers"]
        assert (recorded.kind, recorded.played_s, recorded.listener, recorded.event) == (
            "orientation", 0.0, None, None)
        assert (recorded.overtone, summary["overtone"]) == ("neutral", "neutral")
        assert recorded.tone is not None
        assert (summary["kind"], summary["tone"], summary["listens"]) == ("orientation", recorded.tone, False)
        assert (summary["agenda"], summary["slot"], summary["direction"]) == (None, None, None)
        assert (summary["heard"], recorded.heard) == (None, None)
        assert summary["trimmed"] == []
        assert (recorded.tokens, recorded.trims) == (None, [])

    def test_a_free_round_records_its_event_and_overtone(self, client, show_env, fake_model):
        run_id = _start(client)["run_id"]
        _round(client, run_id)
        summary = _summary(_round(client, run_id, played_s=5))

        recorded = load_run(run_id).rounds[1]
        assert (recorded.kind, summary["kind"]) == ("free", "free")
        assert recorded.event is not None and summary["event"] == recorded.event
        assert recorded.overtone == summary["overtone"]
        assert recorded.event in [e for items in _pools()[recorded.overtone].values() for e in items]

    def test_the_request_carries_the_plan_budget_and_round_seed(self, client, show_env, fake_model):
        run_id = _start(client)["run_id"]
        _round(client, run_id)

        call = fake_model[0]
        recorded = load_run(run_id).rounds[0]
        assert call["max_tokens"] == 512
        assert call["seed"] == 42 + 1
        assert call["grammar"].splitlines()[:2] == [
            "root    ::= pinned line{0,1}", 'pinned  ::= "Samantha" " (" emotion "): " text "\\n"']
        assert [m["role"] for m in call["messages"]] == ["system", "user"]
        assert call["messages"][1]["content"] == recorded.instruction

    def test_the_next_round_reads_the_reply_back_exactly(self, client, show_env, fake_model):
        run_id = _start(client)["run_id"]
        _round(client, run_id)
        _round(client, run_id)

        second = fake_model[1]["messages"]
        assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
        assert second[2]["content"] == REAL_TEXT
        assert fake_model[1]["seed"] == 42 + 2
        assert len(load_run(run_id).rounds) == 2

    @pytest.mark.parametrize("run_id", ["2026-09-24T01-23-45", "../../etc", "nope"])
    def test_unknown_or_malformed_run_is_404(self, client, show_env, run_id):
        resp = client.post("/api/show/round", json={"run_id": run_id})
        assert resp.status_code == 404

    def test_an_error_mid_stream_records_nothing(self, client, show_env, monkeypatch):
        async def failing_stream_round(messages, *, grammar, max_tokens, seed):
            for token in REAL_ROUND[:10]:
                yield {"token": token}
            raise RuntimeError("the model went away")

        monkeypatch.setattr(show_router, "stream_round", failing_stream_round)
        run_id = _start(client)["run_id"]

        events = _round(client, run_id)

        assert [e["type"] for e in events][-2:] == ["error", "complete"]
        assert "the model went away" in sse_events_by_type(events, "error")[0]["message"]
        assert load_run(run_id).rounds == []


def _pools():
    """The shipped story's events by overtone, then theme."""
    return yaml.safe_load((SHIPPED_STORIES / "lab-outbreak" / "events.yaml").read_text())["events"]


def _to_the_call(client):
    """A run whose second round is the Repair: the sign-on, then the call once the cadence's maximum has played."""
    run_id = _start(client)["run_id"]
    _round(client, run_id)
    call = _summary(_round(client, run_id, played_s=180))
    assert (call["kind"], call["listens"]) == ("repair", True)
    return run_id, call


class TestFixedLines:
    def test_the_call_is_said_in_fixed_lines_without_asking_the_model(self, client, show_env, fake_model):
        run_id = _start(client)["run_id"]
        _round(client, run_id)
        events = _round(client, run_id, played_s=180)

        done = sse_events_by_type(events, "done")
        assert [(e["persona"] == "Samantha", e.get("fixed")) for e in done] == [(False, True), (True, True)]
        assert all(e["text"].endswith(" Over.") for e in done)
        assert len(fake_model) == 1
        repair = load_run(run_id).rounds[1]
        assert (repair.kind, [line.fixed for line in repair.lines]) == ("repair", [True, True])
        assert [line.spoken for line in repair.lines] == [e["text"] for e in done]
        assert repair.timings is None

    def test_the_last_answer_then_the_breakdown_opening_with_the_operators_fixed_line(self, client, show_env,
                                                                                     fake_model):
        app_config._settings_cache.show = ShowConfig(seed=42, contact_exchanges=1, contact_jitter=0)
        run_id, _ = _to_the_call(client)
        last = _summary(_round(client, run_id, played_s=190, transcript="Moira, is it airborne?"))
        assert (last["kind"], last["listens"], last["receiver"]) == ("last-exchange", False, True)

        events = _round(client, run_id, played_s=200)

        summary = _summary(events)
        assert (summary["kind"], summary["listens"], summary["receiver"], summary["direction"]) == (
            "breakdown", False, False, "Smoke pours from the receiver, and it goes dead.")
        done = sse_events_by_type(events, "done")
        assert (done[0]["persona"], done[0].get("fixed")) == ("Samantha", True)
        assert not any(e.get("fixed") for e in done[1:])
        breakdown = load_run(run_id).rounds[-1]
        assert breakdown.kind == "breakdown" and breakdown.lines[0].fixed
        assert fake_model[-1]["messages"][-1]["content"].startswith(
            'Something happens that the listeners cannot see, and Samantha has just told them on air: "')


class TestListenerTurn:
    def test_the_call_then_the_exchange_that_answers_the_transcript(self, client, show_env, fake_model):
        run_id, call = _to_the_call(client)
        exchange = _summary(_round(client, run_id, played_s=190, transcript="Moira, is it airborne?"))

        assert call["direction"] == "The receiver crackles back to life."
        assert (exchange["kind"], exchange["speakers"], exchange["listens"]) == ("exchange", CAST, True)
        assert exchange["answers"][0] == 1 and call["answers"] is None
        assert exchange["agenda"].startswith("Find out who the voice is.")
        _, repair, answered = load_run(run_id).rounds
        assert (repair.kind, repair.played_s) == ("repair", 180.0)
        assert (answered.kind, answered.played_s, answered.listener) == ("exchange", 190.0, "Moira, is it airborne?")
        assert answered.agenda == exchange["agenda"]
        assert len(fake_model) == 2  # The sign-on and the exchange: the call is said in fixed lines
        assert fake_model[1]["grammar"].splitlines()[1].startswith('pinned  ::= "Moira"')
        messages = fake_model[1]["messages"]
        assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]  # The call joins the turn
        assert messages[-1]["content"].startswith("Something happens that the listeners cannot see, and ")
        assert ('" Then a voice on the frequency says: "Moira, is it airborne?" Speak to the voice directly. '
                'Answer what the voice said, then: Find out who the voice is.' in messages[-1]["content"])

    def test_a_silent_window_gives_the_re_call(self, client, show_env, fake_model):
        run_id, _ = _to_the_call(client)
        summary = _summary(_round(client, run_id, played_s=190))

        assert (summary["kind"], summary["heard"], summary["listens"]) == ("re-call", None, True)
        assert load_run(run_id).rounds[2].instruction.startswith(
            "Only static answers. Samantha calls out once more to anyone listening, asking them to answer now; the "
            "receiver is still on.")

    def test_a_transcript_outside_a_listening_window_is_ignored(self, client, show_env, fake_model, caplog):
        run_id = _start(client)["run_id"]
        with caplog.at_level(logging.WARNING):
            summary = _summary(_round(client, run_id, transcript="Moira, is it airborne?"))

        assert summary["kind"] == "orientation"
        assert load_run(run_id).rounds[0].listener is None
        assert "outside a listening window" in caplog.text


class TestTranscriptFilter:
    """After a listening round, what Whisper heard becomes words (an exchange) or silence (a re-call), recorded
    either way."""

    @pytest.mark.parametrize("text, no_speech_prob, avg_logprob, reason", [
        ("", None, None, "nothing heard"),
        ("Hello there.", 0.9, -0.2, "no speech (no_speech_prob 0.90 > 0.6)"),
        ("Hello there.", 0.1, -1.5, "an unsure reading (avg_logprob -1.50 < -1.0)"),
        ("Thank you.", 0.1, -0.2, "a known Whisper hallucination"),
        ("No response received from STT server", None, None, "a known Whisper hallucination"),
    ])
    def test_whisper_noise_gives_the_re_call(self, client, show_env, fake_model, text, no_speech_prob,
                                             avg_logprob, reason):
        run_id, _ = _to_the_call(client)
        summary = _summary(_round(client, run_id, played_s=190, transcript=text, no_speech_prob=no_speech_prob,
                                  avg_logprob=avg_logprob))

        assert summary["kind"] == "re-call"
        recorded = load_run(run_id).rounds[2]
        assert recorded.listener is None
        assert (recorded.heard.text, recorded.heard.silence) == (text, reason)
        assert summary["heard"] == recorded.heard.model_dump()

    def test_clear_words_give_the_exchange_and_are_recorded(self, client, show_env, fake_model):
        run_id, _ = _to_the_call(client)
        summary = _summary(_round(client, run_id, played_s=190, transcript="Moira, is it airborne?",
                                  no_speech_prob=0.05, avg_logprob=-0.3))

        assert summary["kind"] == "exchange"
        recorded = load_run(run_id).rounds[2]
        assert recorded.listener == "Moira, is it airborne?"
        assert recorded.heard.model_dump() == {"text": "Moira, is it airborne?", "no_speech_prob": 0.05,
                                               "avg_logprob": -0.3, "silence": None}
        assert summary["heard"] == recorded.heard.model_dump()


class TestListen:
    AUDIO = base64.b64encode(b"fake webm audio").decode()

    @pytest.fixture
    def whisper(self, monkeypatch):
        """Turn STT on and fake the show's transcription; keep each call's arguments."""
        app_config._settings_cache.stt = STTConfig(enabled=True, base_url="http://stt.local:6600")
        calls = []

        async def fake_transcribe_for_show(audio_bytes, mime_type="audio/webm", *, prompt=None, language=None):
            calls.append({"audio": audio_bytes, "mime": mime_type, "prompt": prompt, "language": language})
            return {"text": "Moira, is it airborne?", "no_speech_prob": 0.05, "avg_logprob": -0.3,
                    "words": [{"word": "Moira,", "probability": 0.8}, {"word": "is", "probability": 0.99},
                              {"word": "it", "probability": 0.97}, {"word": "airborne?", "probability": 0.45}]}

        monkeypatch.setattr(show_router, "transcribe_for_show", fake_transcribe_for_show)
        return calls

    def test_transcribes_with_the_casts_names_and_the_language(self, client, show_env, whisper):
        run_id = _start(client)["run_id"]

        resp = client.post("/api/show/listen", json={"run_id": run_id, "audio_base64": self.AUDIO})

        assert resp.status_code == 200
        assert resp.json() == {"text": "Moira, is it airborne?", "no_speech_prob": 0.05, "avg_logprob": -0.3,
                               "words": [{"word": "Moira,", "probability": 0.8}, {"word": "is", "probability": 0.99},
                                         {"word": "it", "probability": 0.97},
                                         {"word": "airborne?", "probability": 0.45}]}
        assert whisper[0] == {"audio": b"fake webm audio", "mime": "audio/webm",
                              "prompt": "Daniel, Moira, Ralph, Samantha", "language": "en"}

    def test_stt_off_is_503(self, client, show_env):
        run_id = _start(client)["run_id"]
        resp = client.post("/api/show/listen", json={"run_id": run_id, "audio_base64": self.AUDIO})
        assert resp.status_code == 503

    def test_bad_audio_is_400_and_an_unknown_run_404(self, client, show_env, whisper):
        run_id = _start(client)["run_id"]
        assert client.post("/api/show/listen", json={"run_id": run_id, "audio_base64": "abc"}).status_code == 400
        assert client.post("/api/show/listen", json={"run_id": "nope", "audio_base64": self.AUDIO}).status_code == 404

    def test_a_failed_transcription_is_502(self, client, show_env, monkeypatch):
        app_config._settings_cache.stt = STTConfig(enabled=True, base_url="http://stt.local:6600")

        async def failing(*args, **kwargs):
            return None

        monkeypatch.setattr(show_router, "transcribe_for_show", failing)
        run_id = _start(client)["run_id"]

        resp = client.post("/api/show/listen", json={"run_id": run_id, "audio_base64": self.AUDIO})

        assert resp.status_code == 502

class TestTrim:
    def test_a_full_script_is_trimmed_before_the_round(self, client, show_env, monkeypatch):
        app_config._settings_cache.show = ShowConfig(seed=42, context_budget=1000)
        requests = []

        async def fake_stream_round(messages, *, grammar, max_tokens, seed):
            requests.append(messages)
            for token in REAL_ROUND:
                yield {"token": token}
            yield {"timings": {"prompt_n": 100, "cache_n": 500, "predicted_n": 50}, "finish_reason": "stop"}

        monkeypatch.setattr(show_router, "stream_round", fake_stream_round)
        run_id = _start(client)["run_id"]
        run = load_run(run_id)
        lines = [Line(**dataclasses.asdict(line)) for line in REAL_LINES]
        for n in range(1, 11):
            append_round(run, Round(n=n, instruction=f"Instruction {n}.", speakers=["Ralph", "Moira"],
                                    max_lines=2, lines=lines, tokens=100))
        run.rounds[-1].timings = {"prompt_n": 900, "cache_n": 0, "predicted_n": 50}
        save_run(run)

        summary = _summary(_round(client, run_id))

        assert summary["trimmed"] == [3, 4, 5, 6]
        sent = [m["content"] for m in requests[0]]
        assert not any(f"Instruction {n}." in sent for n in (3, 4, 5, 6))
        assert all(f"Instruction {n}." in sent for n in (1, 2, 7, 8, 9, 10))
        recorded = load_run(run_id)
        assert [r.n for r in recorded.rounds if r.trimmed] == [3, 4, 5, 6]
        assert recorded.rounds[-1].trims == [3, 4, 5, 6]
        assert recorded.rounds[-1].tokens == 650 - (950 - 400)


class TestDebug:
    @pytest.fixture
    def debug_server(self, monkeypatch):
        """Fake the model server's /apply-template and /tokenize; the count matches FINAL's prompt size."""
        async def render_prompt(messages):
            return "RENDERED PROMPT"

        async def count_tokens(text):
            return 4 + 303

        monkeypatch.setattr(show_debug, "render_prompt", render_prompt)
        monkeypatch.setattr(show_debug, "count_tokens", count_tokens)

    def test_debug_on_leaves_both_files_per_round(self, client, show_env, fake_model, debug_server):
        app_config._settings_cache.show = ShowConfig(seed=42, debug=True)
        run_id = _start(client)["run_id"]
        _round(client, run_id)
        _round(client, run_id)

        folder = runs_root() / run_id / "debug"
        assert sorted(p.name for p in folder.iterdir()) == [
            "r001.request.json", "r001.txt", "r002.request.json", "r002.txt"]
        request = json.loads((folder / "r002.request.json").read_text(encoding="utf-8"))
        assert request["messages"] == fake_model[1]["messages"]
        assert (request["grammar"], request["max_tokens"], request["seed"]) == (
            fake_model[1]["grammar"], 512, 42 + 2)
        text = (folder / "r002.txt").read_text(encoding="utf-8")
        assert "difference 0" in text
        assert "RENDERED PROMPT" in text
        assert "".join(REAL_ROUND) in text

    def test_debug_off_leaves_nothing(self, client, show_env, fake_model):
        run_id = _start(client)["run_id"]
        _round(client, run_id)

        assert not (runs_root() / run_id / "debug").exists()

    def test_a_failed_round_leaves_its_debug_file(self, client, show_env, monkeypatch, debug_server):
        app_config._settings_cache.show = ShowConfig(seed=42, debug=True)

        async def failing_stream_round(messages, *, grammar, max_tokens, seed):
            for token in REAL_ROUND[:10]:
                yield {"token": token}
            raise RuntimeError("the model went away")

        monkeypatch.setattr(show_router, "stream_round", failing_stream_round)
        run_id = _start(client)["run_id"]
        _round(client, run_id)

        text = (runs_root() / run_id / "debug" / "r001.txt").read_text(encoding="utf-8")
        assert "error: the model went away" in text
        assert "".join(REAL_ROUND[:10]) in text
        assert load_run(run_id).rounds == []

    def test_a_client_leaving_while_the_files_are_written_still_gets_them(self, client, show_env, fake_model,
                                                                          monkeypatch):
        """Seen live on 2026-09-25: a Stop after the round was recorded cut its debug files short."""
        app_config._settings_cache.show = ShowConfig(seed=42, debug=True)
        run, story = show_router._load(_start(client)["run_id"])
        written = []

        async def scenario():
            started, release = asyncio.Event(), asyncio.Event()

            async def slow_write_round(run_id, n, kind, messages, **kwargs):
                started.set()
                await release.wait()
                written.append(n)

            monkeypatch.setattr(show_router, "write_round", slow_write_round)

            async def consume():
                async for _ in show_router._round_stream(run, story, ShowRoundRequest(run_id=run.run_id)):
                    pass

            task = asyncio.create_task(consume())
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            release.set()
            for _ in range(5):
                await asyncio.sleep(0)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(scenario())
        finally:
            loop.close()

        assert written == [1]
        assert [r.n for r in load_run(run.run_id).rounds] == [1]
