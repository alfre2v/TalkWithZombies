# Runbook: play the show in the browser

*Living, undated. Written 2026-09-25 with step 3.1 of the show engine's
slice 3 (the page with text only), grown with 3.2 (the voice) and 3.3
(the listener's turn), and with the page's looks. `GET /show` is the
chooser (`templates/show_choose.html`): a card per look, each with a live
miniature. The plain page is `GET /show?design=plain`
(`templates/show.html`, with its own files in `static/show/`); a design is
`GET /show?design=<name>` (see "Choosing a look" below). The
plan it follows lives in the companion repository,
[alfre2v/zombie-radio](https://github.com/alfre2v/zombie-radio)
(`docs/discussions/2026-09-25-show-slice-3-browser-plan.md`); to play
rounds without a browser, see [show-driver.md](show-driver.md).*

All commands run from this repository's root,
`/Users/alfredo/workspace/hackTNT_2026/TalkWithZombies`.

## What you need

The same as for the driver ([show-driver.md](show-driver.md), "What
you need"): the model services and the SSH tunnel, the app's
dependencies in `.venv`, and a `settings.yaml` pointing at the
tunnel's ports and at a personas folder with a reference voice for
every cast member.

## Open the page

Start the app (it serves the page too):

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
```

Then open <http://127.0.0.1:8010/show> (the root, <http://127.0.0.1:8010/>,
sends you there too), choose a look, and press **Start**. The page opens a run, puts the story's title and cast in
place, and plays rounds one after another until you press **Stop**.

## The show's settings: the demo, or a test show

The show reads its settings from the `show:` section of `settings.yaml`,
in the folder the app runs from — this checkout's, or the installed
client's, `~/TalkWithZombies-client/settings.yaml`. **A show needs no
`show:` section at all:** every setting has a default, and the defaults
are the demo's configuration. The four switches worth knowing:

| Setting | Default | What it does |
|---|---|---|
| `debug` | `false` | On: the debug line under each round, the model's debug files, and every chunk the voice said, in `runs/<run-id>/debug/` (see "The debug line") |
| `seed` | none: a random one per run | A number: the model writes the same story every run |
| `mood_voices` | `true` | Each line is spoken with its mood's reference clip; off, every line with `ref.wav` (see "The voice") |
| `voice_seed` | `false` | On: every chunk is spoken with the run's seed — with `seed` set, the same voices every run too (see "The voice") |
| `bed` | `true` | Radio static played quietly under the show, in the looks, from the clips in `Sounds/bed/`; off, none (see "The static bed") |

The rest of the section — about 40 numbers for the pacing, the
listener's turn and the contacts — has tuned defaults; they are listed,
with what each does, in `app/config.py` (`ShowConfig`).

**For a test show**, add what you need under `show:` and restart the app
(the settings are read when it starts):

```yaml
show:
  debug: true        # the debug line, and every chunk's audio kept
  seed: 42           # optional: the same story every run
  voice_seed: true   # optional, with seed: the same voices every run too
```

**Back to the demo:** delete those lines (or the whole `show:`
section) and restart the app.

To see what a settings file sets for the show:

```bash
# The show section of this checkout's settings (no output: no show section, the demo's defaults)
grep -A5 '^show:' settings.yaml
```

For example, this checkout on 2026-09-30:

```
show:
  seed: 42
```

`mood_voices`, `voice_seed` and the kept audio arrive with the fork's
`tz-0.4` (alfre2v/TalkWithZombies#8); an older version ignores settings
it does not know, without a word, so a `voice_seed: true` there does
nothing.

## Choosing a look

`/show` offers every design of `static/show/designs/`, in the order their
`design.yaml` gives, then the plain page. The same show runs in each; only
the look changes:

- **Old radio** — <http://127.0.0.1:8010/show?design=old-radio>: a photo
  of a 1950 Philips Sirius (credits in the design's `CREDITS.md` and on the
  page). The transcript runs on the speaker cloth; the magic eye glows
  while the receiver is on and closes with the sound; the dial lights on
  air; the knob of the character speaking glows; the keys sit on the
  walnut side panels.
- **Amateur radio transmitter** —
  <http://127.0.0.1:8010/show?design=amateur-radio-transmitter>: the
  transcript on an oscilloscope whose trace swings with the sound; the
  PLATE meter follows the voices, the SIGNAL meter your microphone.
- **Plain** — <http://127.0.0.1:8010/show?design=plain>: the working page
  with no visuals. Any other name also gives the plain page.

Under the cards, a link leads to TalkWithMe's chat UI, the interface this
project is built upon: <http://127.0.0.1:8010/talkwithme> (it used to be the
root page).

A design's gauge is `static/show/gauge.js`: loaded only by designed pages,
it reads the sound's level from the voice and, while you hold the button,
from your microphone. Add `&mock=1` to a design's address to see it
filled with a recorded stretch of a show, without running one (the
chooser's miniatures do this). If a design looks out of date after a
change, the browser is holding its old files: reload with Cmd+Shift+R.

## What you see

- **The header:** the story's title, the cast strip (the speaker is lit
  while their voice plays), the **ON AIR** sign (lit while the show
  runs), the **RECEIVER** sign (lit while the lab's receiver works, so
  the radio may call on you), and under them the **Captions** toggle.
- **The script:** one block per round — the event, or a receiver beat
  (the story's stage direction for the Repair, the Breakdown, the
  Switch-off), as a stage direction in brackets, then the lines
  (speaker, mood, spoken text). A line appears when its voice starts.
  The stage direction appears above the round's lines when the round's
  summary arrives, usually a moment before the first voice.
- **The bottom bar:** Start / Stop / Resume, the state (Thinking…,
  On air, Listening… N s, Stopped, Error), and the **Hold to talk**
  button.
- **Captions** hide or show the lines and the stage directions
  together; the choice is remembered by this browser. The lines keep
  being added while hidden.

## How the show runs

Step 3.4c's director (the fork's `app/show/director.py`; zombie-radio's
`docs/discussions/2026-09-26-show-director-modes.md`). The numbers are
the defaults, all in `settings.yaml` under `show:`.

- **Broadcast — the receiver is down.** The cast talk among
  themselves; every few rounds an event (something the listeners cannot
  see) is read out on air, word for word, by one of the cast, and the
  others react. The show opens with the operator's sign-on:
  who the cast are, where they are, and that they can only transmit for
  now. An orientation repeats it for newcomers every 20 ± 5 free rounds
  (`orientation_every`), opened by whoever has been silent longest.
- **The call.** 60 to 180 seconds of audio after the receiver went off
  (`interaction_min_s`, `interaction_max_s`), someone tells you what
  just happened to the receiver, and the operator tells you the lab can
  hear you now and calls out; the RECEIVER sign lights with the call,
  and the radio listens.
- **Contact — someone answered.** The character you named answers you
  first (else whoever asked you last), then the cast ask you something:
  who you are first, then what they need (the story's `agenda.yaml`) —
  and they remember what you said, earlier callers included. After each
  exchange the radio listens again. The answer that ends the contact —
  after 5 ± 1 of them (`contact_exchanges`) — gets the last exchange:
  they answer you, ask nothing, and the radio does not listen. The
  Breakdown follows at once: the receiver fails, the operator tells you
  they can no longer hear you but go on broadcasting, and the others
  react; the RECEIVER sign, still lit through the last exchange, goes
  dark.
- **Silence.** A silent window gets a re-call: before anyone answered,
  the operator calls once more; inside a contact, whoever was talking
  calls you back and repeats the question. Two silences in a row
  (`silences_to_switch_off`), and the operator switches the receiver
  off — to save power, or to spare it for a better time — and tells you
  they will not hear you until it is back on; the broadcast goes on.
- **After a contact** the next round talks about what you said (the
  aftermath); every 15 ± 5 free rounds (`recollection_every`) the cast
  recall a past caller and imagine how they could help if they call
  again.
- **The mood.** Each round has an overtone — positive, neutral or
  negative (the story's `overtones.yaml`) — which sets the moods its
  lines may carry and its tone word: the call is hopeful, a contact
  hopeful or level, a Breakdown level or grim; the broadcast drifts
  between neighbors, a stretch at a time.
- **Fixed lines** (`fixed_lines`, on). The lines the listener must not
  miss are not left to the model: the event read out, the call (both of
  its lines), and the Breakdown's and the Switch-off's opening lines are
  said word for word by the cast — the event's own text, and
  for the receiver the story's `beats.yaml` (four versions of each,
  drawn without repeats). The model writes the lines around them, and
  sees them in the script like any other; a call is not sent to the
  model at all. Off, the model writes every line.

## The voice

- **Each line goes to the voice as soon as it is written.** It is cut
  into chunks of whole sentences, up to about 100 characters ("Testing.
  1. 2. 3. Over." is one chunk; a sentence longer than 100 goes whole
  and alone; a chunk never crosses into the next line, which is another
  voice). A sentence ends where `.`, `!`, `?` or `…` meet a space or the
  line's end, so "3.5" or "e.g." reach the voice as written. The chunks are synthesized one at a time through the app's
  `/api/tts`, in the speaker's persona voice, the next while the current
  one plays, and played in order: 80 ms between the chunks of a line,
  250 ms after each line.
- **The voice follows the mood** (`mood_voices`, on). Each line is
  spoken with the reference clip of its mood, as the story's
  `overtones.yaml` declares under `voices` — `afraid: ref-fear.wav`,
  `calm: ref.wav`, one for each of its moods. The clips live in each
  persona's folder, named after what was recorded (`ref-fear.wav` is the
  voice dataset's "fear"), each with its transcript (`ref-fear.txt`);
  they are cast there by zombie-radio's tools, which copy every recording
  a speaker has (its runbook `docs/runbooks/cast-voices.md`, "With every
  emotion"), so the story can remap a mood without a recast. The page learns the
  map when the run starts and names the clip with every chunk of the
  line; a clip a persona lacks, or a story without `voices`, falls back
  to the persona's `ref.wav`. Off (`mood_voices: false` under `show:`),
  every line uses `ref.wav`, as before — for an A/B by ear.
- **The run's seed for the voice** (`voice_seed`, off). The voice engine
  draws each chunk from a random seed; a chunk sent without one gets a
  new random seed from the engine every time (Faster Qwen3-TTS picks one
  in 1..1000 and says which in its reply), so the same line said twice
  can sound different. A seed does not make a voice better or steadier:
  the same clip, text and seed give the same audio, byte for byte, a bad
  chunk as much as a good one. What it gives is a run said the same way
  twice:
  - off (the default): no seed is sent; the engine picks one per chunk,
    as before this setting existed. Any chunk can still be said again
    exactly with the debug folder (below), from the seed the engine said
    it used.
  - `voice_seed: true` under `show:`: every chunk is asked for with the
    run's seed (`seed:` under `show:`, or the random one the run drew).
    With `seed:` set, the model already writes the same script; with
    this on, the voice says it the same way too — for comparing two
    runs that differ in one thing only (a clip, a remapped mood, a
    recast), or re-saying a recorded show.

  The app fits the run's seed into the range the engine advertises for
  `seed` in its capabilities (a seed within the range is kept as it is;
  outside, it wraps around: 4000000001 becomes 1 in 1..1000), and sends
  nothing to an engine that advertises no `seed`. The show's seed wins
  over a `seed` under `tts.parameters` (which the chat uses). Decided
  2026-09-30, after a per-chunk seed was built and dropped: no strategy
  for the seed makes the voices steadier, and one seed per run is the
  simplest that replays a run.
- **The next round is asked for when the voice has said everything**,
  with the seconds of audio played so far — the sum of the clips'
  lengths — so the director's cadence counts what the listener heard.
  A clip cut by Stop does not count.
- **A chunk the voice cannot say** is skipped (the browser console
  says why; with debug on, the round notes it); its line still appears
  at its turn, and the show goes on.
- **Text only:** add `&voice=off` to a look's address (for example
  <http://127.0.0.1:8010/show?design=plain&voice=off>) to play
  without voices, on the simulated clock of step 3.1: after each round
  the page waits as long as its lines would take to say, about 15
  characters a second, and reports that as played seconds. Useful to
  watch the director without the TTS, or while it is down.

## The static bed

Under the voices, the looks play **radio static**, quietly: a few clips
of shortwave hiss, tuning sweeps and distant stations, one after another
in a shuffled order — the receiver's own noise, always there. (A *bed*,
in sound production, is a quiet layer under the foreground, moved up and
down around it.)

- **Where:** in the looks (`?design=old-radio`,
  `?design=amateur-radio-transmitter`). The plain page stays silent, the
  working page, unless you ask: add `&bed=on` to its address
  (<http://127.0.0.1:8010/show?design=plain&bed=on>). Not with `&mock=1`.
- **The volume:** `bed_volume_voice` and `bed_volume_between` are plain
  multipliers on the sound's amplitude, not decibels: 0 is silence, 1 the
  clips' common level (every clip first brought to the same average level
  by its own gain). In dB, 20 × log₁₀(value): 0.15 is −16.5 dB, 0.05 is
  −26 dB. To make the whole bed quieter, multiply both by the same
  factor, so the dip keeps its shape: × 0.5 (0.075 / 0.025) is −6 dB,
  half the amplitude; × 1/3 (0.05 / 0.017) about −9.5 dB, which sounds
  about half as loud. `bed_dip_s` and `bed_rise_s` are the seconds a
  change takes.
- **How loud, and when:** low while a round is said
  (`bed_volume_voice`, 0.05), higher while the page waits — for the next
  round, for you to press, for Whisper (`bed_volume_between`, 0.15). It
  dips in `bed_dip_s` (0.5 s) and rises in `bed_rise_s` (1.5 s), never
  jumps. **Silent while you hold to talk** (at once, so the microphone
  does not hear it), back when you let go. With `bed_off_in_contact:
  true`, also silent while the RECEIVER sign is lit.
- **Start, Stop, Resume:** it rises from silence at Start; Stop pauses
  it at once, and Resume picks the same clip up where it stopped. The
  show has no end of its own — it runs until Stop.
- **The M key mutes it** (and unmutes it), with a short fade — for the
  presenter, if the room's speakers make it too much; nothing shows on
  the page. The voice is never muted by it.
- **The clips** are radio static from Freesound, kept outside git in
  `Sounds/bed/` (beside `Personas/`, ignored by git): the clips as
  downloaded, and `bed.json`, which lists them with **a gain each** that
  brings every clip to the same average level (measured on the mono mix
  the page plays), so the shuffle never jumps in level. `bed.json` holds
  facts about the files, never edited by hand: it is written by
  zombie-radio's `tools/sounds/prepare_bed.py`, which copies there the
  clips its list `tools/sounds/bed.yaml` names — its runbook-in-place is
  the sound-effects discussion,
  `/Users/alfredo/workspace/hackTNT_2026/zombie-radio-claude/docs/discussions/2026-10-01-sound-effects.md`,
  §8.14 and §8.16. **No `Sounds/bed/bed.json`, no bed** — the show runs as
  before.
- **Which clips play is the story's choice:**
  `stories/lab-outbreak/bed.yaml` lists the clips by file name, each
  `enabled: true` or `false`, with `gain_db` — a change of its level by
  ear, in dB, added to the measured gain: **0 changes nothing** (the
  shipped file sets it on every clip), `-3` is a little quieter, `-6`
  half the amplitude, `+6` twice it:

  ```yaml
  clips:
    # Shortwave Radio static with indistinguishable foreign chatter and static (CC BY 4.0, 172 s)
    - file: 730109-shortwave-radio-static-with-indistinguishable-foreign-chatte.mp3
      enabled: true
      gain_db: 0
    # morse static.wav (CC BY 4.0, 5 s)
    - file: 34418-morse-static.mp3
      enabled: false
      gain_db: 0
  ```

  **The story is read when a run opens:** change a line, **reload the
  show page and press Start**, and the new run plays the new list — no
  restart of the app, unlike the settings (`settings.yaml` is read once,
  when the app starts). Start shows only on a fresh page; Resume
  continues the same run, with the list it opened with. A clip
  enabled there but missing from `Sounds/bed/` is skipped (the app's log
  says so); a misspelled key or a bad value refuses the start with the
  line at fault ("bed.yaml does not know enable …"); without the file,
  every clip in `Sounds/bed/` plays.
- **Which clip is playing:** with `debug: true`, the browser's console
  (Developer Tools) says what the bed does — each clip as it starts, with
  its place in the shuffled pass and its gain, each new shuffle, and the
  M key. The lines have this form (the file and its gain are clip
  730109's, as `bed.json` gives them; a real run's order is its own
  shuffle):

  ```
  Show: bed shuffled: a new pass of 17 clips
  Show: bed clip 1 of 17: 730109-shortwave-radio-static-with-indistinguishable-foreign-chatte.mp3 (gain +9.4 dB)
  Show: bed muted (M)
  ```

  With debug off (the demo), it says nothing.
- **Mono, in the browser:** the clips are not changed; the page mixes
  each stereo clip down to one channel, (left + right) / 2, as it plays —
  a radio's speaker.
- **The gauge** (the magic eye, the meters) follows the voices only; the
  static never moves it.
- **Each clip is streamed** by an `<audio>` element from
  `/api/show/bed/<file>`, never decoded whole: 24 minutes of static
  would take about half a gigabyte of memory decoded.

To see the bed the app would give a run:

```bash
# The static bed in a start reply: how many clips, its settings, and the first clip (opens a run in runs/)
curl -s -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8010/api/show/start | python3 -c "import json,sys; b=json.load(sys.stdin)['bed']; print(len(b['clips']), 'clips', {k: v for k, v in b.items() if k != 'clips'}); print(b['clips'][0])"
```

For example, this checkout on 2026-10-01 (17 clips prepared):

```
17 clips {'volume_voice': 0.05, 'volume_between': 0.15, 'dip_s': 0.5, 'rise_s': 1.5, 'off_in_contact': False}
{'file': '11859-analog-noise-arped-radio-static.mp3', 'gain': 0.7453}
```

`null` instead means `bed: false`, no clip in `Sounds/bed/`, or none of
them enabled by the story's `bed.yaml`.

## Talk back

- **The microphone** is asked for once, when you press Start (the
  browser shows its permission prompt then, not in the middle of a
  listening window). It is open only while the radio listens.
- **After the call, and after each exchange or re-call** has been said,
  the listening window opens: the state shows "Listening… N s" for
  `show.listen_window_s` seconds (10 by default) and the **Hold to
  talk** button lights up.
- **Hold the button (or the space bar) while you speak**, and let go
  when you are done. The window stops counting; the state shows
  "Recording… N s", counting down `show.press_cap_s` (30 by default),
  which ends a press held too long. On release the state shows
  "Hearing…" while Whisper transcribes, and the next round answers you:
  the character you named, else whoever asked you last.
- **No press before the window ends** counts as silence: a re-call, or
  after two in a row the Switch-off (see above). A transcription that
  fails counts as silence too.
- **What Whisper heard shows at once**, under the round that listened, as a
  caption line: `You: Hello Samantha, are you there?`. Each word is
  marked by how sure Whisper was of it: plain from 80 %, a dotted
  underline from 50 %, dimmed with a wavy underline below; hover over a
  word for its percentage. If the words count as silence, the caption
  says why once the next round starts — for example `You: Thank you.
  (counted as silence: a known Whisper hallucination)`; an empty
  recording shows `You: (nothing heard)`. The captions toggle hides it
  with the other lines.
- With debug on, the block of the round that listened also shows how long hearing
  took (`heard "…" in 0.4 s`), and the next round's debug line whether
  it counted as words or as silence, and why.
- **If the browser pane will not give the page the microphone**, open
  <http://127.0.0.1:8010/show> in Chrome.

## The debug line

With `debug: true` under `show:` in `settings.yaml` (restart the app),
each round gets a small line under it: the round's number and kind,
its overtone, the allowed speakers, the event, the tone word, what
filled the event slot (`aftermath`, `recollection`), the agenda item an
exchange asked, a contact's answers so far (`answers 2 of 3`), what was heard, the
trimmed and dropped rounds, the seconds to the first line and to the
round's end, and — once the round has been said — the seconds from the
round's request to its first sound (the silence the listener hears
between rounds), the seconds of audio it played, and the reference clip
each line was spoken with (`voices Moira ref-fear.wav, Daniel ref.wav`,
as the app reports it); then the run id —
the run's record is
`runs/<run-id>/script.json`. The debug files of the driver's runbook
are written too.

### Every chunk the voice said, kept

With debug on, the page also tags each chunk's voice request with its
run and place (`debug: "2026-09-30T18-51-36/r001-l1-c1"`), with
`voice_seed` on or off, and the app
keeps the chunk in the run's folder, `runs/<run-id>/debug/audio/`, as
two files named after the place, the persona and the clip spoken with:

- `r001-l1-c1-Daniel-ref-fear.wav` — the audio exactly as the engine
  returned it, the one the page played;
- `r001-l1-c1-Daniel-ref-fear.json` — what made it: the text, the
  persona, the language, the clip the page asked for and the clip used,
  that clip's file and SHA-256 (so a recast after the run shows), its
  transcript, the seed the page asked for (`seed_asked`: none with
  `voice_seed` off, and before the app fitted it into the engine's
  range), and the engine's reply without the audio (the seed it used,
  `time_used`, the sample rate), with the time it was kept.

The audio takes 48 KB per second of speech (24 kHz, 16-bit, mono); a
50-round run keeps an estimated 35-45 MB (`runs/` is not in git). Without
debug, or for a request without the tag (TalkWithMe's chat), nothing is
kept; a tag that is not a run's and a place's, or names a run without a
folder, keeps nothing either — the tag can name no other folder.

To find a line you heard go wrong: its text is in the run's
`script.json` and in the `.json` files; the place gives the round and
the line.

```bash
# Every chunk of round 1, with the seed the engine used and its text
for f in runs/2026-09-30T18-51-36/debug/audio/r001-*.json; do python3 -c "import json,sys; k=json.load(open(sys.argv[1])); print(sys.argv[1].rsplit('/',1)[1], k['reply'].get('seed'), k['text'])" "$f"; done
```

For example (the live check of 2026-09-30: two chunks sent by hand, the
first with no seed, as `voice_seed` off sends it, the second with
4000000001, which the app fitted to 1):

```
r001-l1-c1-Daniel-ref-fear.json 97 Candles! We found candles in the supply closet. Over.
r001-l1-c2-Daniel-ref-fear.json 1 Candles! We found candles in the supply closet. Over.
```

### Say a chunk again

`scripts/replay_chunk.py` asks the app (`/api/tts`, while it is serving)
for a kept chunk again, the way the page asked: the same persona, clip
and text, and the same seed — the one the page sent, or, with
`voice_seed` off, the one the engine said it used. The app builds the
engine's request as it did during the show (the seed fitted, the
`tts.parameters`), and the answer is written beside the chunk as
`<chunk>.replay-seed<N>.wav`. It says whether the new audio is
byte-identical to the kept one: for a given clip, text and seed the
engine answers the same, so a difference means something else changed
(the engine, its library, the settings). If the clip's file changed
since the run (a recast), it says so and asks nothing. An engine that
neither receives a seed nor says which it used cannot be replayed
exactly: give one with `--seed`.

```bash
# Say one chunk again, with the seed it was said with (the app must be serving)
python3 scripts/replay_chunk.py runs/2026-09-30T18-51-36/debug/audio/r001-l1-c1-Daniel-ref-fear.json
```

For example:

```
r001-l1-c1-Daniel-ref-fear.json: seed 97 (kept: 97), 3.28 s (kept: 3.28 s), engine 1.1230215200012026 s; byte-identical to the kept chunk
  -> runs/2026-09-30T18-51-36/debug/audio/r001-l1-c1-Daniel-ref-fear.replay-seed97.wav
```

```bash

# Say it with another seed, to hear whether the seed is to blame
python3 scripts/replay_chunk.py runs/2026-09-30T18-51-36/debug/audio/r001-l1-c1-Daniel-ref-fear.json --seed 42
```

## Stop, Resume, and a reload

- **Stop** abandons the round in flight (the server records nothing for
  it; the page marks it "stopped mid-round"), cuts the voice, and cuts a
  wait short. A
  Stop can land just after the server recorded the round, before its
  summary reached the page: after Resume, the next round's number tells,
  and the note becomes "stopped, but the server kept this round" — the
  model reads that round from then on. (Seen once, 2026-09-25, on a
  double Stop; the round's debug files are written either way.)
- **Resume** continues the same run: the next round is the one that was
  stopped or failed; after a round that listens, the listening window
  opens first.
- **A reload** starts over: Start opens a new run. The old run's record
  stays in `runs/`.

## When something looks wrong

- **"Error: the show could not start: …"** — the app could not open a
  run: a persona without a reference voice (the message names it), a
  story that does not load, or **a budget the model server cannot hold**:
  "show.context_budget … does not fit the model server's context of …
  tokens", with the arithmetic. The app asks the server its context
  (llama.cpp's `/props`) when a run opens; the script may grow to
  `trim_trigger` of `context_budget`, plus `instruction_room` for the next
  instruction and `max_tokens` for the reply, and all of it must fit. It
  happens when the box runs a smaller context than the settings expect —
  for example a target deployed with `zr_llama_ctx` 16384 while the budget
  is the 32k one (34,000). Lower `context_budget` under `show:` (with the
  defaults, the context must be at least 32,112 tokens for 34,000; for a
  16,384 context, a budget of about 16,500 fits), or redeploy the box with
  a larger context. Fix it and press Start again.
- **"Error: the round request failed …" or a failed round** — the model
  did not answer: check the tunnel (`curl localhost:8080/health` must
  say `{"status":"ok"}`), then press **Resume**; the failed round is
  asked for again.
- **Nothing happens on Start** — the app is not serving, or the browser
  console (Developer Tools) shows why.
- **No static under the show** — the plain page without `&bed=on`;
  `bed: false`; no `Sounds/bed/bed.json` (the start reply's `bed` is
  `null`: run zombie-radio's `tools/sounds/prepare_bed.py --write`); every
  clip `enabled: false` in the story's `bed.yaml`; the M key pressed; or
  `&voice=off` (no voice, no bed). The browser console
  says when a clip would not load ("the static bed could not play", or
  "no clip of the static bed would load" when none would).
- **The talk button never lights up** — the microphone was refused or
  is missing: allow it in the browser's site settings and reload (a
  reload starts a new run); the windows still count down, and each
  counts as silence (a re-call, then the Switch-off).
- **Lines appear but no sound** — check the browser's sound and the
  TTS (`curl -s -o /dev/null -w '%{http_code}' localhost:8001/capabilities`
  must say 200); with debug on, each round notes the chunks the voice
  could not say.
