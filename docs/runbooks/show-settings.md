# Runbook: the show's settings — recipes

*Living, undated (runbooks convention). What to change to get something done:
each recipe gives the lines to put under `show:`, what else it needs, and how to
see that it took effect. The complete list of the settings, with what each one
does, is the comments of `ShowConfig` in `app/config.py`; this runbook only
holds recipes. How the page behaves is in
[`show-page.md`](show-page.md).*

## How a setting changes

1. **Open the app's `settings.yaml`** — in the folder the app runs from: the
   installed client's `~/TalkWithZombies-client/settings.yaml`, or a
   checkout's own. The show's settings go under a `show:` section. **No `show:`
   section at all is the demo:** every setting has a default, and the defaults
   are the demo's configuration. Every setting, at its default and with a few
   words on what it does: `settings.example.yaml`, in the app's folder.
2. **Add or change the lines** of a recipe below, under `show:` (two spaces of
   indent). Several recipes can be combined in one `show:` section.
3. **Restart the app** — the settings are read once, when it starts: stop
   uvicorn (Ctrl+C in its terminal) and start it again, from the app's folder:

   ```bash
   # Start the app again (the installed client's port; a dev checkout may use another)
   .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

4. **Reload the show page and press Start** — a new run takes the new
   settings.

**Two kinds of change need no restart:**

- **The story's files** (`stories/lab-outbreak/`, for example `bed.yaml`, which
  switches the static's clips on and off) are read when a run opens: change
  the file, reload the page, press Start. Resume continues the same run, with
  what it opened with.
- **The address switches and the keys** (below) work at once.

**A misspelled setting is ignored without a word** (the app reads the names it
knows), and a value out of its bounds stops the app at start, naming it. To see
what a settings file sets for the show:

```bash
# The show section of a settings file (no output: no show section, the demo's defaults)
grep -A20 '^show:' settings.yaml
```

To see what the app will give a run — the start reply carries the settings the
page uses — see "The static bed" in [`show-page.md`](show-page.md) for a ready
command; note that each call opens a run in `runs/`.

## The demo, or a test show

**The demo:** no `show:` section (or delete the lines you added). The static
bed on, no debug files, a new story every run.

**A test show** — see what happened, and play the same story again:

```yaml
show:
  debug: true        # the debug line under each round; the model's files and every voice chunk kept in runs/<run-id>/debug/; the bed's console lines
  seed: 42           # the model writes the same story every run (with the same answers and timing)
  voice_seed: true   # optional: the voice says each line the same way every run too
```

Check: the debug line appears under each round; with the browser's console
open (Developer Tools), the bed names each clip it plays.

## The voices follow the mood

Each line is spoken with the reference clip of its mood: the story's
`overtones.yaml` names a clip per mood (`afraid: ref-fear.wav`, `calm:
ref.wav`), and each persona's folder holds its own recording of each. That is
`mood_voices` (on). Off, every line is spoken with the persona's `ref.wav`,
whatever its mood — the same voice, without the emotion:

```yaml
show:
  mood_voices: false   # every line with ref.wav
```

More: [`show-page.md`](show-page.md), "The voice".

## The voice's reference clips, compressed

Every line the voice says is sent with its character's reference clip. The
clips are WAVs of about 450-650 KB; their Opus copies are about 8 times
smaller, which matters on a slow uplink (a crowded venue's Wi-Fi):

```yaml
show:
  reference_format: ogg   # send each clip's compressed copy (ref-fear.ogg beside ref-fear.wav); wav sends the originals
```

**First, make the copies** — from zombie-radio's clone, with its tool, which
writes an `.ogg` beside every `ref.wav` and `ref-<word>.wav` of the cast and
never touches the WAVs
(`/Users/alfredo/workspace/hackTNT_2026/zombie-radio-claude/tools/voices/compress_voices.py`):

```bash
# From zombie-radio's clone: an Opus copy (48 kbps) beside every reference clip of the cast
uv run python tools/voices/compress_voices.py
```

A clip without its copy is sent as its WAV, so a missing copy never breaks a
line. The copies share the clips' transcripts and names: the story still says
`ref-fear.wav`.

**Back to the originals, even during a show:** `reference_format: wav` (or
delete the line) and restart the app; the copies can stay on disk.

Check: with `debug: true` too, each voice chunk's record in
`runs/<run-id>/debug/audio/` names the file sent (`"clip"`) — it ends in
`.ogg`.

## The static bed

The radio static under the show, in the looks (`?design=old-radio`,
`?design=amateur-radio-transmitter`). Its two volumes are **plain multipliers
on the sound's amplitude, not decibels**: 0 is silence, 1 the clips' common
level. In dB, 20 × log₁₀(value): −6 dB is half the amplitude; −10 dB sounds
about half as loud.

### Make the static quieter (or louder)

Multiply **both** volumes by the same factor, so the dip under the voices
keeps its shape (the "between" level stays 3 times the "voice" level):

| How much | `bed_volume_between` | `bed_volume_voice` | Change |
|---|---|---|---|
| the default | 0.15 (−16.5 dB) | 0.05 (−26.0 dB) | — |
| a little quieter (× 2/3) | 0.10 | 0.035 | about −3.5 dB |
| half the amplitude (× 1/2) | 0.075 | 0.025 | −6 dB |
| about half as loud (× 1/3) | 0.05 | 0.017 | about −9.5 dB |
| louder (× 1.5) | 0.225 | 0.075 | about +3.5 dB |

For example, half the amplitude:

```yaml
show:
  bed_volume_between: 0.075
  bed_volume_voice: 0.025
```

### A deeper, or a gentler, dip under the voices

The dip is the ratio of the two volumes. Keep `bed_volume_between`, change
`bed_volume_voice`: 0.05 is a third (−9.5 dB, the default); 0.015 is a tenth
(−20 dB, the static nearly gone under a line); 0.1 is two thirds (−3.5 dB,
hardly a dip). How fast it moves: `bed_dip_s` (0.5 s, down) and `bed_rise_s`
(1.5 s, back up).

```yaml
show:
  bed_volume_voice: 0.015   # nearly silent under a line
  bed_dip_s: 0.3            # and quicker to get out of the way
```

### No static at all

For the whole show:

```yaml
show:
  bed: false
```

Live, for a moment: **the M key** mutes and unmutes it (no restart, nothing
shows on the page). Through every contact only (from the Repair to the
Breakdown or the Switch-off):

```yaml
show:
  bed_off_in_contact: true
```

### More rest for the ear — or fewer breaks

The silences: every random time in `bed_silence_every_s` the static fades out
(over `bed_silence_fade_s`) and pauses for a random time in `bed_silence_s`,
then goes on where it stopped. Defaults: every 30-120 s, for 3-15 s. Ranges
are `[min, max]` in seconds; a single value is `[x, x]`.

```yaml
show:
  bed_silence_every_s: [20, 60]   # more often
  bed_silence_s: [5, 20]          # and longer
```

No silences:

```yaml
show:
  bed_silences: false
```

### A steadier, or a livelier, signal (the fading)

The fading (radio amateurs' QSB, the signal swelling and sinking): every random
time in `bed_fading_every_s` the level glides to a new one within ±
`bed_fading_db` decibels. Defaults: ±3 dB every 2-6 s.

```yaml
show:
  bed_fading_db: 0      # steady: no fading
```

```yaml
show:
  bed_fading_db: 6                 # a stormy band
  bed_fading_every_s: [1.5, 4]
```

### The AM filter — an old radio's narrow band

The filter keeps only `bed_filter_low_hz` to `bed_filter_high_hz` of the
static: the hiss's sharp top and its rumble go. **The F key** flips it on and
off live, to compare by ear; the setting decides how a run starts. The
default band is the telephone's; narrower bands sound more like a shortwave
receiver with poor reception, and tire the ear less (it is most sensitive
around 2-5 kHz):

| Try | `bed_filter_low_hz` | `bed_filter_high_hz` | What to expect |
|---|---|---|---|
| the default | 300 | 3000 | a telephone's band: clean |
| A, shortwave voice | 300 | 2700 | a ham's SSB voice filter: the classic shortwave sound |
| B, a narrow receiver | 400 | 2000 | tinny and boxy, clearly "radio"; much less hiss |
| C, poor reception | 500 | 1500 | a cheap, distant receiver |
| D, the extreme | 600 | 1000 | close to a Morse filter: almost a tone |

For example, B, on from the start:

```yaml
show:
  bed_filter: true
  bed_filter_low_hz: 400
  bed_filter_high_hz: 2000
```

A narrower band also sounds quieter (less passes): for a fair comparison,
raise both volumes a little with it.

### The static on the plain page

The plain page (`?design=plain`) stays silent as the working page. Add
`&bed=on` to its address: `/show?design=plain&bed=on`. No setting, no restart.

### Switch a clip off, or change one clip's level by ear

Not a setting: the story's `stories/lab-outbreak/bed.yaml`, one entry per
clip. `enabled: false` switches it off; `gain_db` changes its level by ear, in
dB (0 changes nothing, −3 a little quieter, −6 half the amplitude). Then reload
the page and press Start — no restart.

```yaml
  # The Sound of dial-up Internet (CC0 1.0, 29 s)
  - file: 546450-the-sound-of-dial-up-internet.mp3
    enabled: false
    gain_db: 0
```

With `debug: true`, the browser's console names each clip as it starts, with
its file name — the name to look for in `bed.yaml`.

## The ambience

The world outside the lab, under the show in the looks (and on the plain page
with `&bed=on`): the dead moaning, gunfire and explosions, screams, a storm.
**Textures** (long, continuous) play one after another; **spots** (short,
single events) come now and then, on top. It goes through the static's AM
filter (the F key flips both) and has its own volumes, silences and fading,
never in step with the static's. The clips ship with the app in
`Sounds/ambience/`; which of them play is the story's
`stories/lab-outbreak/ambience.yaml`.

### Make the ambience quieter (or louder)

Its volumes are plain multipliers, like the static's: the default is
`ambience_volume_between` 0.3 and `ambience_volume_voice` 0.12 (under a
line) — twice the static's level between rounds, more than twice under a
line. The clips are measured to the same average level as the static's, but a
low moan or a distant rumble sounds much quieter than a hiss of the same
energy, and the hiss masks it: at the static's own volumes (0.15 and 0.05) the
ambience was barely heard (the owner's ear, 2026-10-07). Change both by the
same factor to keep the dip's shape; for example half the amplitude:

```yaml
show:
  ambience_volume_between: 0.15
  ambience_volume_voice: 0.06
```

### More spots, fewer, or louder

A spot comes after a random wait in `ambience_spot_every_s` (20-60 s), at
`ambience_spot_volume` times a texture's level (1.0):

```yaml
show:
  ambience_spot_every_s: [10, 30]   # twice as often
  ambience_spot_volume: 1.5         # a little louder than the textures
```

`ambience_spots: false` keeps the textures alone.

### A deeper, or a gentler, dip under the voices (the ambience)

As the static's: the dip is the ratio of the two volumes (`ambience_volume_voice`
0.12 under a line, `ambience_volume_between` 0.3 between rounds), and two
settings say how fast it moves: `ambience_dip_s` (0.8 s, down when a line
starts) and `ambience_rise_s` (2.5 s, back up). The ambience rises more slowly
than the static (1.5 s), so the world outside creeps back in after a line:

```yaml
show:
  ambience_dip_s: 0.4    # out of the way faster
  ambience_rise_s: 4     # and back more slowly
```

### More rest for the ear — or fewer breaks (the ambience's silences)

As the static's, on timers of their own, never in step with them: every
random time in `ambience_silence_every_s` (45-150 s) the textures fade out
(over `ambience_silence_fade_s`, 2 s) and pause for a random time in
`ambience_silence_s` (5-20 s), then go on where they stopped. Only the
textures fall silent: a spot may still come out of the silence. Ranges are
`[min, max]` in seconds.

```yaml
show:
  ambience_silence_every_s: [30, 90]   # more often
  ambience_silence_s: [10, 30]         # and longer
```

No silences: `ambience_silences: false`.

### A steadier, or a livelier, world outside (the ambience's fading)

As the static's fading, on its own timer: every random time in
`ambience_fading_every_s` (5-15 s) the level glides to a new one within ±
`ambience_fading_db` decibels (±4 dB). 0 keeps it steady:

```yaml
show:
  ambience_fading_db: 0     # steady
```

Every setting of the ambience, at its default, with a line on each:
`settings.example.yaml`, in the app's folder.

### One clip louder, quieter, or off

In the story's `ambience.yaml`, a clip's `gain_db` (`-6` half the amplitude,
`+6` twice) or `enabled: false`. Read when a run opens: reload the show page
and press Start, no restart.

### Sound cues: an event that names a sound plays it

A clip in the story's `ambience.yaml` may have `keywords:` — the words or
phrases of an event that cue it. When a free round's event says one (a whole
word or phrase, any case), the clip plays as the event is read aloud: a spot
at once, a texture in place of the current one, to its end (then the shuffle
goes on). Several clips matched: one of them, picked with the run's seed, so a
seed replays its cues. For example, the explosions:

```yaml
clips:
  - file: explosion-4.mp3
    enabled: true
    gain_db: 0
    keywords: [explosion, explosions, explodes, exploded, exploding, detonation, detonates]
```

Keep them precise — a loose word plays a sound where it does not belong
("blast" is also a blast door; "the moaning stops" names a moan) — and list
each form: "explosion" does not match "explosions".

A sound that belongs to its event — a helicopter, a train horn — and should
never pass by at random gets `cue_only: true` (it needs keywords): it is left
out of the textures' shuffle and the random spots, and plays only when an
event cues it.

```yaml
clips:
  - file: helicopter-1.mp3
    enabled: true
    gain_db: 0
    keywords: [helicopter, helicopters]
    cue_only: true
```

A cue switches nothing on:
with `ambience: false`, `ambience_spots: false`, a clip off, or the A key's
mute, it is not heard. Read when a run opens: reload the page and press Start.

To hear cues more often while testing, an event in every free round:

```yaml
show:
  event_every: 1
  event_jitter: 0
```

### No ambience at all

For the whole show:

```yaml
show:
  ambience: false
```

Live, for a moment: **the A key** mutes and unmutes it (the static goes on).

## The listener's turn

**More time to start talking** after the radio calls (the countdown before the
window closes; 10 s by default), and **a longer answer** (how long one press
may record; 30 s):

```yaml
show:
  listen_window_s: 15
  press_cap_s: 45
```

**The radio calls sooner, or later.** After the receiver goes off, the next
Repair (the receiver back, the radio calling for listeners) comes after
`interaction_min_s` to `interaction_max_s` seconds of show played (60-180 s by
default) — never before the minimum, always by the maximum:

```yaml
show:
  interaction_min_s: 30    # calls come sooner
  interaction_max_s: 90
```

**Longer, or shorter, conversations** with a listener: a contact lasts
`contact_exchanges` (± `contact_jitter`) of the listener's answers (5 ± 1);
after `silences_to_switch_off` silences in a row (2), the receiver is switched
off (the Switch-off):

```yaml
show:
  contact_exchanges: 3     # shorter contacts
  silences_to_switch_off: 1
```

**Longer, or shorter, answers from the cast.** Each exchange — the cast
answering what the listener said, ending on a question — is
`contact_min_lines` to `contact_max_lines` lines (2-3):

```yaml
show:
  contact_min_lines: 1     # quicker back-and-forth
  contact_max_lines: 2
```

**How much the cast remember of earlier callers.** A contact's instruction
restates what the voices of the last `restatement_contacts` contacts said (5),
so the cast can come back to it:

```yaml
show:
  restatement_contacts: 2  # only the last two callers
```

**A listener speaking another language.** `stt_language` is the language
Whisper listens for (`en`); the cast still speak English, as the story is
written:

```yaml
show:
  stt_language: es
```

**Whisper hears silence, or invents words.** A press counts as silence — and
the radio calls again — when Whisper heard nothing, when it heard one of its
known inventions ("Thank you for watching"), or when one of two thresholds says
so: `no_speech_max` (0.6), Whisper's probability that nobody spoke, above which
the press is silence; and `logprob_min` (−1.0), Whisper's average confidence in
its reading, below which it is silence too. Real answers counted as silence (a
quiet speaker, a noisy room): loosen them; invented words getting through:
tighten them.

```yaml
show:
  no_speech_max: 0.8       # looser: fewer presses thrown away as silence
  logprob_min: -1.5
```

The app's log always says why a press counted as silence, with what Whisper
heard (`no speech (no_speech_prob 0.72 > 0.6)`, for example). One price of the
known inventions: a listener who really says just "Thank you." is heard as
silence.

More on the contact's settings: [`show-driver.md`](show-driver.md), "What you
need" (the paragraph on Step 3.4c's settings); on the listener's turn:
[`show-page.md`](show-page.md), "Talk back".

## The story's pace

**Events more, or less, often** — something happens in the lab every
`event_every` (± `event_jitter`) free rounds (2 ± 1); 0 turns them off:

```yaml
show:
  event_every: 4           # half as many events
```

**Fewer orientations** — the cast re-explains who they are every
`orientation_every` (± `orientation_jitter`) free rounds (20 ± 5); 0 keeps
only the sign-on at round 1:

```yaml
show:
  orientation_every: 40
```

**The tone changes more, or less, often.** Each round is told in a tone word
from the story's `overtones.yaml` ("haunted", "comradely"…), kept
`tone_hold` (± `tone_jitter`) rounds (3 ± 1) and not repeated until its list
is used up; 0 turns tone words off:

```yaml
show:
  tone_hold: 6             # a tone lasts longer
```

**Longer, or shorter, rounds among the cast.** A free round's line budget is
drawn from `free_lines`, with the matching `free_line_weights` (1 to 4 lines,
weighted 1:3:3:1, so mostly 2 or 3). A round with an event gets at least 2: the
event read out and a reaction.

```yaml
show:
  free_lines: [2, 3, 4]
  free_line_weights: [1, 2, 2]   # longer conversations, never a single line
```

**The mood swings more, or less, often.** Each free round has an overtone —
positive, neutral or negative — that picks its moods, its tone word and its
event. It is held `overtone_hold` (± `overtone_jitter`) free rounds (4 ± 1),
then drifts to a neighbor, with the weights the story's `overtones.yaml` sets:

```yaml
show:
  overtone_hold: 8         # longer stretches of hope, or of dread
```

**The cast recall earlier callers more, or less, often.** Once a listener has
spoken, every `recollection_every` (± `recollection_jitter`) free rounds
(15 ± 5) the cast remember an earlier caller and imagine how they could help;
0 turns recollections off:

```yaml
show:
  recollection_every: 8
```

**The receiver's beats: longer, or shorter.** The call, the Breakdown and the
Switch-off take `beat_max_lines` lines (2: the key line, then a reaction), and
an orientation up to as many:

```yaml
show:
  beat_max_lines: 3
```

**The key lines said word for word — or written by the model.** With
`fixed_lines` (on), the lines the listener must not miss are said word for word
by a cast member: an event, read out by the round's first speaker; the call;
the Breakdown's and the Switch-off's opening lines (from the story's
`beats.yaml`). The model writes only the reactions. Off, the model writes them
all, and `event_report` (on) decides how it is told an event: on, the
listeners cannot see it, so the first to speak tells them on air what is
happening; off, the older "Offstage: …", where the characters only react — which
a listener cannot follow.

```yaml
show:
  fixed_lines: false       # the model writes every line, events included
```

More on all of these: [`show-driver.md`](show-driver.md), "What you need" (the
paragraphs on the pacing settings and on Step 3.4c's settings), and
[`show-page.md`](show-page.md), "How the show runs".

## The model server's context

The defaults fit a model server with a 32k context (`context_budget` 34,000).
If Start says "show.context_budget … does not fit the model server's context
of … tokens", the server runs a smaller context: for a 16k server (16,384
tokens), a budget of about 16,500 fits (0.9 × 16,500 + 1,000 + 512 = 16,362):

```yaml
show:
  context_budget: 16500
```

A smaller budget makes the show forget older rounds sooner (it trims when the
script nears 90 % of the budget). The arithmetic is in the error message, and in
[`show-driver.md`](show-driver.md), "How the app tracks the script's size, and
when it trims".

**When, and how much, the show forgets.** Every round the model reads the
whole script so far. Before a round that asks the model, when the script
reaches `trim_trigger` of the budget (0.9, so 30,600 tokens), whole rounds stop
being read, from the middle outwards, until it is back to `trim_target` (0.5,
17,000 tokens); the first `trim_keep_first` rounds (2: the sign-on and the one
after) and the last `trim_keep_last` (4) are always kept. The cut rounds stay in
the run's record; the model just stops reading them. After a trim the model
server reads the shortened script afresh, a pause of about 8 s at 32k. A higher
target forgets less each time, but trims more often:

```yaml
show:
  trim_target: 0.7         # forget less at each trim (trims come more often)
  trim_keep_last: 6        # keep more of the latest rounds
```

**The reply's size, and the room for the next instruction.** `max_tokens`
(512) is the most one round's reply may write; a reply cut short by it loses its
unfinished line, which is never spoken (the app's log says so).
`instruction_room` (1,000) is the room kept for the next round's instruction.
Both count in the start's check: `trim_trigger × context_budget +
instruction_room + max_tokens` must fit the model server's context.

```yaml
show:
  max_tokens: 768          # room for longer rounds
```

More: [`show-driver.md`](show-driver.md), "Play rounds" (the trim, as the driver
shows it) and "When something looks wrong" (a dropped line).

## The model's prompt

Three settings shape what the model is told; none needs changing for the
demo's model.

**`model_prefix`** (`/no_think`) starts the system message. Nemotron's chat
template turns `/no_think` into an empty, closed `<think></think>`, so the model
writes the script at once, not reasoning first — and the grammar, which
constrains what the model writes, starts in the script. Another model may need
its own switch, or none:

```yaml
show:
  model_prefix: ""         # no prefix, for a model without a reasoning switch
```

**`emotion_tags`** (on): each line is written `Name (mood): text`, the grammar
allows only the round's moods, and the voice says each line with its mood's
clip. Off, lines are `Name: text`: no moods, so every line is spoken with the
persona's `ref.wav` (as with `mood_voices: false`).

**`episode`** is declared for episodes, which do not exist yet: the app does
not read it, and the cast sheet's `{{ episode }}` placeholder stays empty.
Setting it changes nothing today.

Every setting at its default, with a line on each: `settings.example.yaml`, in
the app's folder.

## The address switches

Added to the show page's address; no restart:

| Address | What it does |
|---|---|
| `/show` | the chooser: a card per look |
| `/show?design=old-radio` | a 1950 Philips Sirius radio (the static bed plays) |
| `/show?design=amateur-radio-transmitter` | a ham operator's rack (the static bed plays) |
| `/show?design=plain` | the plain, working page (silent) |
| `&bed=on` | the static bed on the plain page too |
| `&voice=off` | text only, no voices (and so no static), on a simulated clock |
| `&mock=1` | a design filled with a recorded stretch of a show, to look at it without running one |

## The keyboard shortcuts

On the show page:

| Key | What it does | Where |
|---|---|---|
| **Space** (hold) | talk to the radio; release to send — the same as holding the Hold to talk button | only while the radio listens (the button lit) |
| **M** | mute or unmute the static bed, with a short fade; the voices are never muted | the looks, or the plain page with `&bed=on` |
| **F** | the AM filter on or off, live — for an A/B by ear; the static and the ambience together | the same, once the static plays |
| **A** | mute or unmute the ambience (the world outside), with a short fade; the static goes on | the same, once the ambience plays |

M, F and A ignore a key held down (no repeat) and a key pressed with Cmd, Ctrl or
Alt, so the browser's own shortcuts are left alone.
