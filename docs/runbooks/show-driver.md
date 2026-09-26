# Runbook: drive the show without a browser

*Living, undated. Written 2026-09-24 with the show engine's first slice.
The driver is `scripts/drive_show.py` (Python standard library only): it
plays rounds through the app's show endpoints and prints what streams,
or checks on its own that the model server enforces the screenplay
grammar. The show engine's design and decisions live in the companion
repository, [alfre2v/zombie-radio](https://github.com/alfre2v/zombie-radio)
(`docs/discussions/2026-09-23-show-engine-design.md`).*

All commands run from this repository's root,
`/Users/alfredo/workspace/hackTNT_2026/TalkWithZombies`.

## What you need

- **The model services and the SSH tunnel.** In the zombie-radio
  clone: `make ssh-tunnel ENV=cloud` in a terminal of its own (it stays
  open), then `make check` — three ok lines. The app reaches the
  services on this Mac's `localhost:8080` (llama.cpp), `:8001`
  (tts-serve) and `:8002` (Whisper).
- **The app's dependencies** in `.venv`
  (`python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`).
- **A `settings.yaml`** in this repository's root (gitignored) pointing
  at the tunnel's ports and at a personas folder holding a reference
  voice for every cast member of the story. The one in use:

  ```yaml
  llm:
    base_url: http://localhost:8080
    model: default
    max_tokens: 200
    temperature: 0.8
  tts:
    enabled: true
    base_url: http://localhost:8001
    timeout: 60.0
    streaming: true
    parameters: {}
  stt:
    enabled: true
    base_url: http://localhost:8002
    timeout: 30.0
  general:
    persona_name_mentions: true
    max_persona_replies: 4
    max_turns_for_context: 50
    show_tool_calls: true
    enable_persona_memories: false
    global_system_prompt: ''
    personas_directory: /Users/alfredo/TalkWithZombies-client/Personas
  mcp:
    servers: []
    max_tool_iterations: 8
  show:
    seed: 42
  ```

  `personas_directory` points at the four cast personas the Mac
  installer (`make client-mac` in zombie-radio) created; the app only
  reads that folder (verified 2026-09-24). `show.seed` makes a run
  repeatable — the same seed, story and settings give the same rounds;
  remove it for a random seed per run. Every other `show:` setting
  takes its default (`app/config.py`, `ShowConfig`). The pacing
  settings are the ones most worth trying by ear: `event_every` and
  `event_jitter` (by default an event every 2 free rounds, give or
  take 1) and `tone_hold` and `tone_jitter` (a tone word kept 3
  rounds, give or take 1); 0 in
  `event_every` or `tone_hold` turns events or tone words off.
  `event_report` (on by default since an A/B test on 2026-09-25) words
  an event for the broadcast — the listeners cannot see it, and the
  first to speak tells them on air what is happening; `false` gives
  the older "Offstage: …", where the characters only react, which a
  listener cannot follow.

## Play rounds

Terminal 1 — the app, on port 8010 (8000 is left free for anything else):

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
```

Terminal 2 — the driver:

```bash
python3 scripts/drive_show.py --rounds 10
```

It opens a run, plays the rounds, and prints each line when it is done,
with the seconds since the round's request left, then a summary per
round and totals at the end. From the first real run (2026-09-24):

```
run 2026-09-24T02-18-51 — The Lab at the End of the Frequency — cast Daniel, Moira, Ralph, Samantha — seed 42
  [ 0.81s] Ralph (doubtful): We've lost the main entrance. The chopper didn't even check for us. Over.
  [ 1.12s] Samantha (urgent): There's a perimeter breach near the east labs, something's coming through. Over.
  [ 1.38s] Ralph (terrified): They're not humans. The gear on their uniforms... it's wrong. Over.
round 1: 3 line(s) of Ralph, Samantha · event: A helicopter passes low overhead without slowing down. · dropped: 0 · finish: stop · first line 0.81s, round 1.38s
...
10 rounds · 24 lines · 0 dropped · average round 1.16s · script after the last round: 1164 tokens
record: runs/2026-09-24T02-18-51/script.json
```

- **The record** of each run is `runs/<run-id>/script.json`
  (gitignored), one folder per drive: every round's instruction, the
  speakers and line budget the director chose, the event, each line as
  the model wrote it (`raw`) and as the voice gets it (`spoken`), and
  the model server's `timings`.
- **The printed lines are the spoken text** (typographic punctuation
  normalized, the mood tag shown separately); `raw` in the record keeps
  what the model actually wrote.
- **"script after the last round"** is the size, in tokens, of what the
  model would read next — the number the context trim watches.
- **Since director v1** (2026-09-24, after the run above), each round
  line also names the round's kind (`free`, `invitation`, `answer`,
  `static`) and its tone word. The driver reports the played seconds as
  a running total (`--played` per round), so with the defaults the
  first invitation comes between round 5 and round 10. Without
  `--heard` the driver sends no listener's words, so the round after an
  invitation is the static one; to answer the invitations, see
  [Run the checkpoint](#run-the-checkpoint).
- **The trim.** When the script reaches 90% of `show.context_budget`
  (14,000 tokens by default), the model stops reading whole rounds from
  the middle of the script until it is back to 50%; the first two and
  the last four rounds are always kept. The driver then prints
  `trimmed before this round: rounds ...`. To watch it within a short
  drive, set `context_budget: 1500` under `show:` and drive about 24
  rounds: a trim comes near round 13.
- Stop the app with Ctrl-C in terminal 1.

**Options:** `--base` (the app's address, default
`http://127.0.0.1:8010`), `--rounds` (default 10), `--story` (a folder
in `stories/`, default the settings' `show.story`), `--played` (seconds
of audio each round is taken to play, default 20; the app receives the
running total), `--heard` (what the listener says at the next
invitation; repeat it, one per invitation; `-` is a silent window),
`--speak` (send the `--heard` items spoken and transcribed, not as
text), `--report` (judge the drive against the checkpoint's criteria),
`--runs-dir` (default `runs`).

## Check that the grammar binds

Only the tunnel is needed — not the app:

```bash
python3 scripts/drive_show.py --control
```

It takes the cast sheet of an existing run (the newest in `runs/`, or
the one named with `--run-id <run-id>`), and sends one request straight
to llama.cpp with a grammar that allows a single speaker absent from
the cast, `Operator`, after an instruction naming two cast members.
Every line must come back as Operator's:

```
control, with the cast sheet of runs/2026-09-24T02-18-51/script.json
control reply:
  Operator (urgent): We’re running low on supplies. Over.
  Operator (doubtful): Should we even bother sending for help? Over.
control: PASS — every line is Operator's
```

It opens no run and writes nothing. If `runs/` is empty, play one
drive first; after changing the story or the emotion switch, play one
drive first too, so the cast sheet it borrows is current.

## Look inside a round (the debug switch)

Add `debug: true` under `show:` in `settings.yaml` and restart the app.
Every round then leaves two files in `runs/<run-id>/debug/`:

- **`r005.txt`**, to read: the round's numbers (seed, budget, finish,
  the server's timings), a token check, the grammar, **the prompt
  exactly as the model read it** (special markers included, rendered
  by the model server's `/apply-template`), and the reply as it
  streamed, including any line that was cut or dropped. A failed
  round gets its file too, with the error.
- **`r005.request.json`**, the exact request body. To send it again
  (the tunnel up; the reply comes back as the same stream of `data:`
  lines):

  ```bash
  curl -s localhost:8080/v1/chat/completions -H 'Content-Type: application/json' -d @runs/<run-id>/debug/r005.request.json
  ```

The token check compares the rendered prompt's token count with the
size the server read (`prompt_n + cache_n`); it says `difference 0`
when all is well, and the app's log warns when it is not. Each debug
round costs about 0.35 s more (two extra calls to the model server),
so leave the switch off when timing a drive.

## Run the checkpoint

The show engine's midpoint checkpoint (zombie-radio's `docs/TODO.md`,
"Checkpoint — 2026-09-25") in one drive, without a browser: at least
ten unattended rounds whose speakers and line counts obey the director,
an invitation answered from a listener's words, a silent window giving
the static round, the trim firing, and the debug files written.

**The listener.** After each invitation, the next `--heard` item
answers, in turn; `-` is a silent window. By default the words go into
the next round request as text. With `--speak` they go the real way, as
the page will send them: the app's TTS speaks them in the operator's
voice (`/api/tts`), the show's listen route transcribes them
(`/api/show/listen`, Whisper), and what Whisper heard, with its
confidence, goes into the round request; a silent window sends two
seconds of silence. Without `--heard`, or once the items run out,
nothing is sent and the window counts as silence.

**1. The settings.** Under `show:` in `settings.yaml` (keep a copy of
the file first and put it back after):

```yaml
show:
  seed: 42
  debug: true
  context_budget: 1500
```

Restart the app (terminal 1). `debug` writes the files the report
checks; the small budget makes the trim fire within the drive; the seed
fixes where the invitations fall.

**2. The drive** (terminal 2):

```bash
python3 scripts/drive_show.py --rounds 20 --speak --report --heard "Moira, is the virus airborne?" --heard - --heard "Is anyone still alive in there?"
```

With seed 42 and 20 seconds a round, the invitations fall at rounds 8,
13 and 18 (the cadence depends only on the seed and the played
seconds, not on what the model writes): round 9 answers the question
naming Moira, round 14 is the silent window's static round, round 19
answers a question naming no one, and the trim fires before round 14.
Leave out `--speak` to test without TTS and Whisper.

**3. The report.** From the first run (2026-09-24), the listener's
rounds and the end:

```
round 8 (invitation): 1 line(s) of Samantha · ...
  the listener says "Moira, is the virus airborne?" in Samantha's voice (1.28s); Whisper heard "Moira, is the virus airborne?" (no_speech_prob 0.010, avg_logprob -0.225) in 0.35s
  [ 0.84s] Moira (doubtful): I don't know, maybe. Over.
round 9 (answer): 1 line(s) of Moira · ...
  listener: "Moira, is the virus airborne?"
...
round 14 (static): 1 line(s) of Samantha · ...
  heard: "" -> silence: nothing heard
  trimmed before this round: rounds 3, 4, 5, 6, 7, 8, 9 (the model no longer reads them)
...
checkpoint report, run 2026-09-24T18-56-59:
  PASS  20 of 20 rounds played and recorded (10 needed)
  PASS  speakers and line counts obey the director: 38 lines, 0 dropped
  PASS  an invitation answered from the listener's words: round 9 heard "Moira, is the virus airborne?" -> Moira; round 19 heard "Is anyone still alive in there?" -> Samantha
  PASS  a silent window gave the static round: round 14 (nothing heard)
  PASS  the trim fired: before round 14 (rounds 3, 4, 5, 6, 7, 8, 9)
  PASS  debug files for 20 of 20 rounds; token check difference 0 in 20 of them
6 of 6 criteria pass
```

The report reads the run's record and its `debug/` folder; the driver
exits with 1 when a criterion fails. A FAIL line says what is missing
(no answer, no static round, no trim, the rounds without debug files,
a token check that is not 0). The verdict — continue, scale down or
stop — stays a person's call.

## When something looks wrong

- **The driver cannot connect to port 8010** — the app is not serving:
  start it (terminal 1), or pass `--base` with the address it serves.
- **Starting fails with 422 naming a cast member** — that persona has
  no reference voice (`ref.wav`) in `personas_directory`.
- **A round prints `round error: …`** — the model did not answer: check
  the tunnel (`curl localhost:8080/health` must say `{"status":"ok"}`).
  Nothing is recorded for a failed round; the next drive picks up from
  the record.
- **`dropped` is not 0** — a line was cut short (the round hit
  `show.max_tokens`) or came out malformed; the app's log says which.
  Dropped lines are never spoken and stay out of the history.
- **The control check prints FAIL** — the model server did not enforce
  the grammar. That is a finding about the server, not an operator
  error; keep the output.
