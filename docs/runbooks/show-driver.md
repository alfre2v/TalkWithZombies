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

  **Step 3.4c's settings** (the show's modes; the page's runbook,
  `docs/runbooks/show-page.md`, "How the show runs", says what each
  does): `free_lines` / `free_line_weights` (a free round's line budget,
  1-4 weighted 1:3:3:1; with fixed lines an event round gets at least 2,
  the reading and a reaction); `overtone_hold` / `overtone_jitter` (a free
  round's overtone held 4 ± 1 free rounds, then drifting to a
  neighbor); `contact_exchanges` / `contact_jitter` (a contact lasts
  5 ± 1 of the listener's answers); `contact_min_lines` /
  `contact_max_lines` (an exchange's 2-3 lines);
  `silences_to_switch_off` (2); `beat_max_lines` (the receiver beats'
  2 lines — the Breakdown's and the Switch-off's: the operator's, then a
  reaction; the orientation's up to 2);
  `orientation_every` / `orientation_jitter` (20 ± 5 free rounds; 0
  keeps only the sign-on);
  `recollection_every` / `recollection_jitter` (15 ± 5 free rounds; 0
  turns recollections off); `restatement_contacts` (the earlier
  contacts a contact instruction restates, 5). `interaction_min_s` /
  `interaction_max_s` now count the seconds of audio since the receiver
  went off. The palette itself — the overtones, their moods and tone
  words, the overtones each kind of round may use, the drift's weights
  — is the story's `overtones.yaml`; the events are filed by overtone in
  `events.yaml`; the agenda is `agenda.yaml`. `fixed_lines` (on) has
  the cast say the key lines word for word — an event read out, the
  call, the Breakdown's and the Switch-off's opening lines —
  from the event's text and the story's `beats.yaml`; the driver marks
  them `[fixed]`.

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
  line also names the round's kind and its tone word. **Since step 3.4c
  (director v2)** the kinds are `orientation` (the sign-on at round 1,
  then the repeats), `free`, `repair` (the call; the page listens next),
  `exchange` and `re-call` (the page listens next), `breakdown` and
  `switch-off` (the receiver goes off); a second line under a round
  shows its overtone, what filled its event slot (`aftermath`,
  `recollection`), the agenda item it asked and a contact's answers so
  far. The driver reports the played seconds as a running total
  (`--played` per round), so with the defaults the first call comes
  between round 4 and round 10. Without `--heard` the driver sends no
  listener's words, so every window is silence — a re-call, then the
  Switch-off; to answer, see [Run the checkpoint](#run-the-checkpoint).
- **The trim.** When the script reaches `show.trim_trigger` (90%) of
  `show.context_budget` (34,000 tokens by default), the model stops
  reading whole rounds from the middle of the script until it is back to
  `show.trim_target` (50%); the first `show.trim_keep_first` (2) and the
  last `show.trim_keep_last` (4) rounds are always kept. The driver then
  prints `trimmed before this round: rounds ...`. How the app counts the
  script's size and decides: [How the app tracks the script's size, and
  when it trims](#how-the-app-tracks-the-scripts-size-and-when-it-trims).
  To watch it within a short drive, set `context_budget: 1500` under
  `show:` and drive about 24 rounds: a trim comes near round 13.
- Stop the app with Ctrl-C in terminal 1.

**Options:** `--base` (the app's address, default
`http://127.0.0.1:8010`), `--rounds` (default 10), `--story` (a folder
in `stories/`, default the settings' `show.story`), `--played` (seconds
of audio each round is taken to play, default 20; the app receives the
running total), `--heard` (what the listener says at the next
listening window; repeat it, one per window; `-` is a silent window),
`--speak` (send the `--heard` items spoken and transcribed, not as
text), `--report` (judge the drive against the checkpoint's criteria),
`--runs-dir` (default `runs`).

## How the app tracks the script's size, and when it trims

*The whole story — the questions that led here, the old constants, the
measurements at 16k and 32k, and a survey of every endpoint for testing the
app without the page — is in zombie-radio's
`docs/discussions/2026-10-01-the-app-from-the-outside.md`.*

The show is one growing script: every round, the model reads the whole
script so far (the cast sheet, then each kept round's instruction and
reply) plus the new instruction. That must fit the model server's
context (`-c`, zombie-radio's `zr_llama_ctx`: 32,768 tokens since
2026-10-01). The trim keeps it in.

**The app does not count tokens itself: it takes the model server's own
count, after every round.** When the model finishes a round, llama.cpp's
last streamed chunk carries `timings`, which the app keeps with the round
in `runs/<run-id>/script.json`:

- `prompt_n` — tokens of the prompt the server read fresh this time;
- `cache_n` — tokens of the prompt it reused from its cache (the start
  of the script, unchanged since the last round);
- `predicted_n` — tokens it generated: the reply.

Their sum is **the script's size after that round** — what the model
will read next time, before the next instruction (`script_size()` in
`app/show/script.py`). Each round also records **its share** (`tokens`):
its size less the size before it — what the round added, its
instruction and its reply (`round_share()`).

**Before planning each round, the trim reads the last reported size**
(`trim()`, called by the round route in `app/routers/show.py`):

1. Below `trim_trigger × context_budget` (0.9 × 34,000 = 30,600 by
   default): nothing happens.
2. At or above it: the rounds the model still reads become candidates,
   except the first `trim_keep_first` and the last `trim_keep_last`. The
   middle candidate is flagged `trimmed`, again and again, outwards; each
   one takes **its recorded share** off the size, until the estimate is
   down to `trim_target × context_budget` (17,000) or no candidate is
   left. A flagged round stays in the record, and the model no longer
   reads it.
3. The server reads the shortened script **from the start** — the cache
   holds only an unbroken start, and the middle changed — which is the
   pause after a trim: 8.2 s for 12,209 tokens at 32k (2026-10-01; 5.1 s
   for 5,008 at 16k, 2026-09-28).
4. **The next round's report is the truth.** The shares are an estimate;
   whatever the trim got wrong, the server's next count is the real size,
   and the next decision starts from it — an error never adds up.

Two rounds without a count:

- **A round with no model request** — the Repair, both of its lines
  fixed — has no `timings`: the size is unknown after it, and the trim
  skips that round. The next model round's count includes the Repair:
  its instruction, which quotes its two fixed lines, joins the next
  round's turn (`assemble_messages()` in `app/show/script.py`).
- **Its share, and the next round's, are unknown** (`None`), and the
  trim counts an unknown share as 0. So when trimmed rounds include them,
  the trim **removes more than it estimates and cuts below its target**:
  on 2026-10-01 the script landed at 12,269 tokens, not near 15,500 (50%
  of that run's 31,000). The next round's share shows the correction as
  a negative number (−2,837 below). Harmless — the model just reads a
  little less — and the count is right again from the next round.

**The room above the trigger.** The size the trim watches is the script
*before* the next round; the request also carries that round's
instruction and room for its reply. So a run starts only if
`trim_trigger × context_budget + instruction_room + max_tokens` fits the
server's context, which the app asks the server for (llama.cpp's
`/props`, `n_ctx`) when the run opens; if it does not fit, the run is
refused with the arithmetic in the message:

```
show.context_budget 40000 does not fit the model server's context of 32768 tokens: the trim lets the script reach 36000 tokens (show.trim_trigger 0.9), plus 1000 for the next instruction (show.instruction_room) and 512 for the reply (show.max_tokens) = 37512. Lower show.context_budget, or give the server a larger context.
```

With the defaults, 30,600 + 1,000 + 512 = 32,112 fits 32,768. The
largest share in 82 recorded runs was 741 tokens, an exchange
(instruction and reply); `instruction_room` keeps 1,000. The check runs
once, when a run opens — the server's context changes only when it is
redeployed — so Resume, which continues a run, does not check again. If
the server cannot say, the run starts and the app's log warns.

**Not the tally:** the token check in the debug files (above, [Look
inside a round](#look-inside-a-round-the-debug-switch)) is a separate
verification that the prompt the debug file shows is the one the model
read; the trim never uses it.

To see the tally of a run, round by round:

```bash
# Each round's count from the server, its share, and the trims (the run's record; rounds 111 to 117)
python3 -c "import json,sys; [print(f\"round {r['n']:3} {r['kind']:9} read {(r['timings'] or {}).get('prompt_n','-'):>6} fresh + {(r['timings'] or {}).get('cache_n','-'):>6} cached, wrote {(r['timings'] or {}).get('predicted_n','-'):>4} | share {r['tokens']}\" + (f\" | trimmed before it: {len(r['trims'])} rounds\" if r['trims'] else '')) for r in json.load(open(sys.argv[1]))['rounds'] if int(sys.argv[2]) <= r['n'] <= int(sys.argv[3])]" runs/<run-id>/script.json 111 117
```

For example, the drive of 2026-10-01 (`2026-10-01T12-54-40`, a budget of
31,000):

```
round 111 free      read    194 fresh +  27444 cached, wrote   19 | share 104
round 112 free      read    194 fresh +  27549 cached, wrote   25 | share 111
round 113 free      read    203 fresh +  27653 cached, wrote   50 | share 138
round 114 free      read  12209 fresh +     43 cached, wrote   17 | share -2837 | trimmed before it: 58 rounds
round 115 free      read    209 fresh +  12202 cached, wrote   57 | share 199
round 116 repair    read      - fresh +      - cached, wrote    - | share None
round 117 re-call   read    324 fresh +  12263 cached, wrote   16 | share None
```

Reading it: after round 113 the script is 203 + 27,653 + 50 = 27,906
tokens, past the trigger (0.9 × 31,000 = 27,900), so before round 114 the
trim flags 58 rounds; round 114 reads the shortened script fresh (12,209
tokens, 43 from the cache) — the pause; from round 115 the cache serves
the script again; the Repair (116) has no count, so neither it nor the
re-call after it has a share.

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
a call answered from a listener's words, a silent window giving a
re-call or the Switch-off, the trim firing, and the debug files written
(the criteria reworded for step 3.4c's kinds).

**The listener.** After each round that listens (the call, an
exchange, a re-call), the next `--heard` item answers, in turn; `-` is
a silent window. By default the words go into
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
fixes where the calls fall.

**2. The drive** (terminal 2):

```bash
python3 scripts/drive_show.py --rounds 20 --speak --report --heard "Moira, is the virus airborne?" --heard - --heard "Is anyone still alive in there?"
```

With seed 42 and 20 seconds a round (step 3.4c's director), the first
call falls at round 8 — the cadence depends only on the seed and the
seconds played since the receiver went off, not on what the model
writes. Round 9 is the exchange that answers the question naming Moira
(and asks who the voice is), round 10 the re-call after the silent
window, round 11 the exchange that answers a question naming no one;
with the items used up, round 12 is a re-call, round 13 the Switch-off
and round 14 the aftermath; the next call, round 18, goes unanswered (a
re-call, then the Switch-off). The trim fires before round 10. Leave out
`--speak` to test without TTS and Whisper.

**3. The report.** From a run of 2026-10-01 (run `2026-10-01T14-21-40`; the
fixed lines and the report that sets them apart), the first contact and the end:

```
round 8 (repair): 2 line(s) of Daniel, Samantha · ...
  overtone positive
  the listener says "Moira, is the virus airborne?" in Samantha's voice (1.55s); Whisper heard "Moira, is the virus airborne?" (no_speech_prob 0.009, avg_logprob -0.360) in 0.40s
  [ 0.86s] Moira (calm): The virus isn't airborne, it's *contagious* through proximity. Over.
  [ 1.07s] Daniel (doubtful): Airborne would mean we'd all be dead by now. Over.
  [ 1.28s] Samantha (determined): We need to know who's on the other end. Over.
round 9 (exchange): 3 line(s) of Daniel, Moira, Ralph, Samantha · ...
  listener: "Moira, is the virus airborne?"
  overtone neutral · asks "Find out who the voice is. If the voice already said their name, greet them by it and ask how they found this frequency." · answers 1 of 5
  the listener says nothing (2 s of silence); Whisper heard "" in 0.22s
  [ 0.81s] Samantha (urgent): We need to know who's on the other end. Over.
round 10 (re-call): 1 line(s) of Daniel, Moira, Ralph, Samantha · ...
  heard: "" -> silence: nothing heard
  overtone neutral · answers 1 of 5
  trimmed before this round: rounds 3, 4, 5 (the model no longer reads them)
  the listener says "Is anyone still alive in there?" in Samantha's voice (1.13s); Whisper heard "Is anyone still alive in there?" (no_speech_prob 0.019, avg_logprob -0.193) in 0.36s
  [ 0.89s] Samantha (determined): The dead are at every door. We need help, someone with a vehicle at the south fence. Over.
  [ 1.11s] Daniel (urgent): Can you hear us? We're running out of time. Over.
  [ 1.31s] Moira (curious): Who are you? What can you do? Over.
round 11 (exchange): 3 line(s) of Daniel, Moira, Ralph, Samantha · ...
  listener: "Is anyone still alive in there?"
  overtone neutral · asks "Ask the voice to help get the cast out. The dead are at every door, and the lab needs someone with a vehicle at the south fence. If the voice already offered help, ask what they could bring and how soon." · answers 2 of 5
  [ 1.62s] Moira (curious): We need to know who you are and what you can offer. Over.
...
checkpoint report, run 2026-10-01T14-21-40:
  PASS  20 of 20 rounds played and recorded (10 needed)
  PASS  speakers and line counts obey the director: 42 lines (11 fixed, outside the director's limits), 0 dropped
  PASS  a call answered from the listener's words: round 9 heard "Moira, is the virus airborne?" -> Moira, Daniel, Samantha; round 11 heard "Is anyone still alive in there?" -> Samantha, Daniel, Moira
  PASS  a silent window gave a re-call or the Switch-off: round 10 re-call (nothing heard); round 12 re-call (nothing sent); round 13 switch-off (nothing sent); round 19 re-call (nothing sent); round 20 switch-off (nothing sent)
  PASS  the trim fired: before round 10 (rounds 3, 4, 5); before round 12 (rounds 6, 7); before round 13 (rounds 8); before round 14 (rounds 9); before round 15 (rounds 10); before round 16 (rounds 11); before round 18 (rounds 12, 13)
  PASS  debug files for 20 of 20 rounds; token check difference 0 in 18 of them, no model request in 2 (all lines fixed)
6 of 6 criteria pass
```

The report reads the run's record and its `debug/` folder; the driver
exits with 1 when a criterion fails. A FAIL line says what is missing
(no answered call, no re-call or Switch-off, no trim, the rounds without debug files,
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
