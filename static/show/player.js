/**
 * player.js — The show's voice: each line cut into chunks, the chunks
 * synthesized one at a time and played in order.
 *
 * Copied from upstream's tts.js (its fetch-and-play pipeline), without the
 * chat's audio upload: one fetch at a time,
 * the next chunk fetched while the current one plays. chunks() is the
 * accumulator ruled on 2026-09-22, as a plain function over a whole line:
 * up to 100 characters of whole sentences; a short sentence may ride along
 * up to 120; a longer sentence goes whole and alone; a chunk never crosses
 * a line, since the next line is another voice.
 *
 * A classic script sharing globals, like upstream's; show.js drives it
 * through speakLine, drained, stopVoice and unlockAudio.
 */

const VOICE = {
    chunkMax: 100,             // characters of whole sentences per chunk
    tailMax: 30,               // a sentence shorter than this may ride along...
    tailTolerance: 1.2,        // ...up to chunkMax times this
    pauseInLineMs: 80,         // between the chunks of one line (upstream's gap)
    pauseBetweenLinesMs: 250,  // after a line: the next speaker comes after a beat
};

const voice = {
    ctx: null,          // the AudioContext, created on a click
    pending: [],        // chunks waiting to be synthesized: {persona, text, hooks, first, last}
    ready: [],          // chunks synthesized, waiting to play: the same, plus buffer (null when it failed)
    fetching: false,
    playing: false,
    source: null,       // the clip playing now
    controller: null,   // aborts the synthesis in flight
    onPlayed: null,     // called with each finished clip's seconds
    waiters: [],        // resolvers of drained()
    generation: 0,      // moved on by stopVoice, so the late results of a stopped queue are dropped
};

/* ==========================================================================
   The accumulator (tested in tests/test_show_page.js)
   ========================================================================== */

/**
 * A text's sentences; an unfinished tail counts as a last sentence.
 *
 * A sentence ends at a run of marks (. ! ? …) followed by whitespace or the
 * end of the text, so "3.5", "e.g." and "U.S." stay whole and the pieces
 * rejoin to the text as written. (Upstream's regex, /[^.!?]*[.!?]+/g, also
 * cut inside them, and the chunk sent "Take 3. 5 milligrams." to the voice.)
 */
function sentencesOf(text) {
    const sentences = [];
    const end = /[.!?…]+(?=\s|$)/g;
    let start = 0;
    let match;
    while ((match = end.exec(text)) !== null) {
        const sentence = text.slice(start, end.lastIndex).trim();
        if (sentence) sentences.push(sentence);
        start = end.lastIndex;
    }
    const tail = text.slice(start).trim();
    if (tail) sentences.push(tail);
    return sentences;
}

/**
 * A line cut into the chunks the voice will say, one request each.
 *
 * Whole sentences are packed up to chunkMax characters; a sentence under
 * tailMax may still ride along up to chunkMax * tailTolerance ("Over.");
 * a sentence arriving at an empty chunk goes in whatever its length.
 */
function chunks(line) {
    const out = [];
    let chunk = "";
    for (const sentence of sentencesOf(line)) {
        if (!chunk) {
            chunk = sentence;
            continue;
        }
        const joined = `${chunk} ${sentence}`;
        const fits = joined.length <= VOICE.chunkMax;
        const ridesAlong = sentence.length < VOICE.tailMax && joined.length <= VOICE.chunkMax * VOICE.tailTolerance;
        if (fits || ridesAlong) {
            chunk = joined;
        } else {
            out.push(chunk);
            chunk = sentence;
        }
    }
    if (chunk) out.push(chunk);
    return out;
}

/* ==========================================================================
   The voice queue
   ========================================================================== */

/** Create or wake the audio context; browsers allow sound only after a click, so call it from one. */
function unlockAudio() {
    if (!voice.ctx) voice.ctx = new (globalThis.AudioContext || globalThis.webkitAudioContext)();
    if (voice.ctx.state === "suspended") voice.ctx.resume();
}

/**
 * Queue a line to be said in a persona's voice.
 *
 * hooks.onStart() runs when the line's first chunk starts playing (or at its
 * turn, if no chunk could be synthesized); hooks.onFail(err) runs for each
 * chunk whose synthesis fails — that chunk is skipped.
 */
function speakLine(persona, text, hooks) {
    const parts = chunks(text);
    if (!parts.length) {
        hooks.onStart();
        return;
    }
    parts.forEach((part, i) => {
        voice.pending.push({ persona, text: part, hooks, first: i === 0, last: i === parts.length - 1 });
    });
    synthesizeNext();
}

/** Resolves when every queued line has been said (or the voice was stopped). */
function drained() {
    if (isIdle()) return Promise.resolve();
    return new Promise((resolve) => voice.waiters.push(resolve));
}

/** Stop the voice now: the clip playing is cut, the queues are emptied, the synthesis in flight is abandoned. */
function stopVoice() {
    voice.generation += 1;
    voice.pending = [];
    voice.ready = [];
    voice.fetching = false;
    voice.playing = false;
    if (voice.controller) voice.controller.abort();
    const source = voice.source;
    voice.source = null;
    if (source) {
        try {
            source.stop();
        } catch (e) {
            // Already ended
        }
    }
    wakeWaiters();
}

/** Nothing left to synthesize or play. */
function isIdle() {
    return !voice.fetching && !voice.playing && !voice.pending.length && !voice.ready.length;
}

/** Resolve everyone waiting in drained(). */
function wakeWaiters() {
    const waiters = voice.waiters;
    voice.waiters = [];
    for (const resolve of waiters) resolve();
}

/** Synthesize the next chunk, one at a time, while the current one plays. */
async function synthesizeNext() {
    if (voice.fetching || !voice.pending.length) return;
    voice.fetching = true;
    const item = voice.pending.shift();
    const generation = voice.generation;
    const controller = new AbortController();
    voice.controller = controller;
    let buffer = null;
    try {
        buffer = await synthesize(item.persona, item.text, controller.signal);
    } catch (err) {
        if (!controller.signal.aborted) {
            console.warn("Show voice: a chunk could not be said:", item.persona, item.text, err);
            item.hooks.onFail(err);
        }
    }
    if (generation !== voice.generation) return; // Stopped meanwhile
    voice.fetching = false;
    voice.ready.push({ ...item, buffer });
    playNext();
    synthesizeNext();
}

/** Ask the app's TTS for a chunk in a persona's voice and decode the WAV it returns. */
async function synthesize(persona, text, signal) {
    const resp = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, persona_name: persona }),
        signal,
    });
    if (!resp.ok) throw new Error(`the voice request failed (HTTP ${resp.status})`);
    const data = await resp.json();
    if (!data.audio_base64) throw new Error("the voice returned no audio");
    const binary = atob(data.audio_base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return await voice.ctx.decodeAudioData(bytes.buffer);
}

/** Play the synthesized chunks in order, with a short pause after each; wake drained() at the end. */
async function playNext() {
    if (voice.playing) return;
    if (!voice.ready.length) {
        if (isIdle()) wakeWaiters();
        return;
    }
    voice.playing = true;
    const item = voice.ready.shift();
    const generation = voice.generation;
    if (item.first) item.hooks.onStart();
    if (item.buffer) {
        const whole = await playClip(item.buffer);
        if (generation !== voice.generation) return; // Stopped meanwhile
        if (whole && voice.onPlayed) voice.onPlayed(item.buffer.duration);
        await new Promise((resolve) =>
            setTimeout(resolve, item.last ? VOICE.pauseBetweenLinesMs : VOICE.pauseInLineMs));
        if (generation !== voice.generation) return;
    }
    voice.playing = false;
    playNext();
}

/** Play one clip; resolves true when it ended by itself, false when stopVoice cut it. */
function playClip(buffer) {
    return new Promise((resolve) => {
        const source = voice.ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(voice.ctx.destination);
        source.onended = () => {
            const whole = voice.source === source;
            if (whole) voice.source = null;
            resolve(whole);
        };
        voice.source = source;
        source.start();
    });
}
