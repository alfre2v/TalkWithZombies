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
between rounds) and the seconds of audio it played; then the run id —
the run's record is
`runs/<run-id>/script.json`. The debug files of the driver's runbook
are written too.

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
  run: a persona without a reference voice (the message names it), or
  a story that does not load. Fix it and press Start again.
- **"Error: the round request failed …" or a failed round** — the model
  did not answer: check the tunnel (`curl localhost:8080/health` must
  say `{"status":"ok"}`), then press **Resume**; the failed round is
  asked for again.
- **Nothing happens on Start** — the app is not serving, or the browser
  console (Developer Tools) shows why.
- **The talk button never lights up** — the microphone was refused or
  is missing: allow it in the browser's site settings and reload (a
  reload starts a new run); the windows still count down, and each
  counts as silence (a re-call, then the Switch-off).
- **Lines appear but no sound** — check the browser's sound and the
  TTS (`curl -s -o /dev/null -w '%{http_code}' localhost:8001/capabilities`
  must say 200); with debug on, each round notes the chunks the voice
  could not say.
