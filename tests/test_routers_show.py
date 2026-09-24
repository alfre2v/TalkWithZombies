"""API tests for app/routers/show.py — POST /api/show/start and /api/show/round.

The shipped lab-outbreak story is copied into the test's project root.
The model is faked at the router's import site (app.routers.show.
stream_round) with the real reply recorded on the box on 2026-09-23
(tests/test_show_parser.py), token by token.
"""

import logging
import shutil
from pathlib import Path

import pytest

import app.config as app_config
import app.routers.show as show_router
from app.config import Persona, PersonasConfig, ShowConfig
from app.show.script import load_run
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


def _round(client, run_id, played_s=0, transcript=None):
    resp = client.post("/api/show/round", json={"run_id": run_id, "played_s": played_s, "transcript": transcript})
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

    def test_unknown_story_is_refused(self, client, show_env):
        resp = client.post("/api/show/start", json={"story": "nope"})
        assert resp.status_code == 422

    def test_a_missing_voice_is_refused_and_named(self, client, show_env, monkeypatch):
        voices = [Persona(name=n, system_prompt="-", reference_audio="x") for n in CAST[:3]]
        monkeypatch.setattr(app_config, "_personas_cache", PersonasConfig(personas=voices))

        resp = client.post("/api/show/start", json={})

        assert resp.status_code == 422
        assert "Samantha" in resp.json()["detail"]


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
        assert recorded.event is not None
        assert recorded.speakers == summary["speakers"]
        assert summary["event"] == recorded.event
        assert (recorded.kind, recorded.played_s, recorded.listener) == ("free", 0.0, None)
        assert recorded.tone is not None
        assert (summary["kind"], summary["tone"]) == ("free", recorded.tone)

    def test_the_request_carries_the_plan_budget_and_round_seed(self, client, show_env, fake_model):
        run_id = _start(client)["run_id"]
        _round(client, run_id)

        call = fake_model[0]
        recorded = load_run(run_id).rounds[0]
        assert call["max_tokens"] == 512
        assert call["seed"] == 42 + 1
        assert call["grammar"].splitlines()[0] == f"root    ::= line{{1,{recorded.max_lines}}}"
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


class TestListenerTurn:
    def test_an_invitation_then_the_answer_to_the_transcript(self, client, show_env, fake_model):
        run_id = _start(client)["run_id"]
        invitation = _summary(_round(client, run_id, played_s=180))
        answer = _summary(_round(client, run_id, played_s=190, transcript="Moira, is it airborne?"))

        assert (invitation["kind"], invitation["speakers"]) == ("invitation", ["Samantha"])
        assert (answer["kind"], answer["speakers"], answer["tone"]) == ("answer", ["Moira"], None)
        first, second = load_run(run_id).rounds
        assert (first.kind, first.played_s) == ("invitation", 180.0)
        assert (second.kind, second.played_s, second.listener) == ("answer", 190.0, "Moira, is it airborne?")
        assert fake_model[1]["grammar"].splitlines()[2] == 'speaker ::= "Moira"'
        assert fake_model[1]["messages"][-1]["content"].startswith(
            'A voice on the frequency says: "Moira, is it airborne?" Moira answers the voice:')

    def test_a_silent_window_gives_the_static_round(self, client, show_env, fake_model):
        run_id = _start(client)["run_id"]
        _round(client, run_id, played_s=180)
        summary = _summary(_round(client, run_id, played_s=190))

        assert (summary["kind"], summary["speakers"]) == ("static", ["Samantha"])
        assert load_run(run_id).rounds[1].instruction.startswith("Only static answers. Samantha speaks next:")

    def test_a_transcript_outside_a_listening_window_is_ignored(self, client, show_env, fake_model, caplog):
        run_id = _start(client)["run_id"]
        with caplog.at_level(logging.WARNING):
            summary = _summary(_round(client, run_id, transcript="Moira, is it airborne?"))

        assert summary["kind"] == "free"
        assert load_run(run_id).rounds[0].listener is None
        assert "outside a listening window" in caplog.text
