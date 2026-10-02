/**
 * test_show_bed.js — Tests for the static bed (static/show/bed.js).
 *
 * Run with plain Node (Node 20+, no npm packages, no network):
 *
 *     node tests/test_show_bed.js
 *
 * What it locks in:
 *   - the rules: the shuffle (every clip once per pass, never the clip that just ended first) and the level for
 *     each state of the show;
 *   - the wiring: nothing without a bed in the start reply; with one, each clip streams through an <audio> element
 *     into its gain, the bed's gain (mixed down to mono) and the mute's gain, to the speakers;
 *   - the levels following the show: up between rounds, down while a round is said, silent while the listener
 *     holds to talk, silent while the receiver is on with off_in_contact, paused on Stop and picked up where it
 *     stopped;
 *   - the clips: the next one when a clip ends, a new shuffle when the pass is used up, a failed clip skipped, the
 *     bed given up when every clip fails, a new run's clips;
 *   - the silences (a fade out, the clip paused, the same clip back where it stopped after silence_s; cancelled by
 *     Stop), the AM filter (the bed routed through the band or straight on; the F key flips it live), the fading
 *     (a glide to a new level within plus or minus fading_db every fading_every_s), with fake timers and fixed dice;
 *   - the M key's mute, and the gauge never tapping the bed;
 *   - the plain page's scripts alone define no bed and keep their own functions.
 *
 * How it works: like test_show_gauge.js, the page's scripts (sse.js, player.js, mic.js, show.js) and bed.js are
 * evaluated in a fresh vm.Context, with stubs for the AudioContext, its gain nodes, the <audio> element and the
 * page's elements; each gain's automation calls are recorded.
 *
 * NOTE: this file is intentionally NOT part of the pytest suite. Run it alongside:
 *     python3 -m pytest
 *     node tests/test_show_bed.js
 */

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const SHOW_DIR = path.join(__dirname, "..", "static", "show");
const PAGE_SCRIPTS = ["sse.js", "player.js", "mic.js", "show.js"];

/** An AudioParam stub recording its automation; target() is where the last call sends it. */
function paramStub(value) {
    return {
        value,
        calls: [],
        cancelScheduledValues(t) { this.calls.push(["cancel", t]); },
        setValueAtTime(v, t) { this.calls.push(["set", v, t]); this.value = v; },
        linearRampToValueAtTime(v, t) { this.calls.push(["ramp", v, t]); },
        target() {
            const last = this.calls.filter((c) => c[0] !== "cancel").at(-1);
            return last ? last[1] : this.value;
        },
        lastRamp() { return this.calls.filter((c) => c[0] === "ramp").at(-1) || null; },
    };
}

/** A node's connect and disconnect, recording what it feeds now. */
function connectable() {
    return {
        connected: [],
        connect(n) { this.connected.push(n); return n; },
        disconnect() { this.connected = []; },
    };
}

/** Fake timers: setTimeout queues; fire(ms) runs the first timer set for ms milliseconds, pending() lists them. */
function fakeTimers() {
    const queue = [];
    let id = 0;
    return {
        setTimeout(fn, ms) { queue.push({ id: ++id, fn, ms }); return id; },
        clearTimeout(timer) {
            const i = queue.findIndex((t) => t.id === timer);
            if (i >= 0) queue.splice(i, 1);
        },
        fire(ms) {
            const i = queue.findIndex((t) => Math.abs(t.ms - ms) < 1e-6);
            assert.ok(i >= 0, `no timer of ${ms} ms among ${queue.map((t) => t.ms)}`);
            const [timer] = queue.splice(i, 1);
            timer.fn();
        },
        pending() { return queue.map((t) => t.ms).sort((a, b) => a - b); },
    };
}

/** An AudioContext stub: gain nodes, filters and media element sources that record what they connect to. */
function audioContextClass(made) {
    return class AudioContextStub {
        constructor() {
            this.state = "running";
            this.currentTime = 10;
            this.destination = { name: "speakers" };
            this.gains = [];
            this.filters = [];
            this.elementSources = [];
            this.bufferSources = 0;
            made.push(this);
        }
        resume() {}
        createGain() {
            const node = { gain: paramStub(1), ...connectable() };
            this.gains.push(node);
            return node;
        }
        createBiquadFilter() {
            const node = { type: "lowpass", frequency: paramStub(350), Q: paramStub(1), ...connectable() };
            this.filters.push(node);
            return node;
        }
        createMediaElementSource(element) {
            const source = { element, connected: [], connect(n) { this.connected.push(n); return n; } };
            this.elementSources.push(source);
            return source;
        }
        createBufferSource() {
            this.bufferSources += 1;
            return { connect(n) { return n; } };
        }
        createAnalyser() {
            return { fftSize: 2048, getFloatTimeDomainData(b) { b.fill(0); } };
        }
        createMediaStreamSource() {
            return { connect() {}, disconnect() {} };
        }
    };
}

/** An <audio> element stub: its source, play and pause, and its listeners. */
function audioClass(made) {
    return class AudioStub {
        constructor() {
            this.src = "";
            this.paused = true;
            this.plays = [];
            this.listeners = {};
            made.push(this);
        }
        addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
        fire(type) { for (const fn of this.listeners[type] || []) fn(); }
        play() { this.paused = false; this.plays.push(this.src); return Promise.resolve(); }
        pause() { this.paused = true; }
    };
}

/** A page element stub, enough for setState and setReceiver. */
function elementStub() {
    return {
        textContent: "", hidden: false, disabled: false, children: [],
        classList: { toggle() {} }, setAttribute() {}, appendChild() {},
    };
}

/** A fresh context with the page's scripts, and bed.js (and gauge.js) when asked. */
function load({ withBed = true, withGauge = false } = {}) {
    const contexts = [];
    const audios = [];
    const elements = {};
    const listeners = {};
    const logs = [];
    const timers = fakeTimers();
    const sandbox = {
        console: { log: () => {}, error: () => {}, warn: () => {}, info: (message) => logs.push(message) },
        document: {
            addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); },
            getElementById: (id) => (elements[id] ||= elementStub()),
        },
        navigator: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [] }) } },
        AudioContext: audioContextClass(contexts),
        Audio: audioClass(audios),
        setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout,
        TextDecoder, AbortController, atob, btoa, Blob, performance,
    };
    vm.createContext(sandbox);
    const files = [...PAGE_SCRIPTS, ...(withGauge ? ["gauge.js"] : []), ...(withBed ? ["bed.js"] : [])];
    for (const file of files) {
        vm.runInContext(fs.readFileSync(path.join(SHOW_DIR, file), "utf8"), sandbox, { filename: file });
    }
    const get = (expression) => vm.runInContext(expression, sandbox);
    const key = (code, extra = {}) => {
        for (const fn of listeners.keydown || []) fn({ code, repeat: false, preventDefault() {}, ...extra });
    };
    if (withBed) get("bed").random = () => 0.5; // The dice land in the middle of every range
    return { sandbox, contexts, audios, get, key, logs, timers };
}

const BED_SETTINGS = {
    volume_voice: 0.05, volume_between: 0.15, dip_s: 0.5, rise_s: 1.5, off_in_contact: false,
    silences: true, silence_every_s: [30, 120], silence_s: [3, 15], silence_fade_s: 1,
    filter: false, filter_low_hz: 300, filter_high_hz: 3000, fading_db: 3, fading_every_s: [2, 6],
};

/** A run with a bed of these clips (all gain 1 unless given), as the start reply brings it. */
function startRun(page, clips = ["1-a.mp3", "2-b.mp3", "3-c.mp3"], settings = {}, runId = "run-1", debug = false) {
    page.sandbox.unlockAudio();
    page.get("show").run = {
        run_id: runId,
        debug,
        bed: { ...BED_SETTINGS, ...settings, clips: clips.map((file) => ({ file, gain: 1 })) },
    };
}

/** The bed's stages: the clip's gain, the bed's level, the filter's halves, the fading, the gate and the mute. */
function gains(page) {
    const at = (name) => page.get(`bed.${name}`);
    return { clip: at("clipGain"), layer: at("layer"), highpass: at("highpass"), lowpass: at("lowpass"),
             fading: at("fading"), gate: at("gate"), sounds: at("sounds") };
}

/* ==========================================================================
   The rules
   ========================================================================== */

/** A random() that walks through these values, again and again. */
function cycling(values) {
    let i = 0;
    return () => values[i++ % values.length];
}

test("bedShuffle: every clip once, in an order the random numbers decide", () => {
    const { sandbox } = load();
    for (const n of [1, 2, 5, 17]) {
        const order = sandbox.bedShuffle(n, null, cycling([0.1, 0.7, 0.4, 0.9, 0.2]));
        assert.deepEqual([...order].sort((a, b) => a - b), Array.from({ length: n }, (_, i) => i));
    }
    assert.deepEqual([...sandbox.bedShuffle(0, null)], []);
});

test("bedShuffle: never starts with the clip that just ended, whatever the random numbers", () => {
    const { sandbox } = load();
    for (const n of [2, 3, 17]) {
        for (let last = 0; last < n; last++) {
            for (const r of [0, 0.25, 0.5, 0.75, 0.999]) {
                const order = sandbox.bedShuffle(n, last, () => r);
                assert.notEqual(order[0], last, `n=${n} last=${last} r=${r}`);
                assert.equal(new Set(order).size, n);
            }
        }
    }
    assert.deepEqual([...sandbox.bedShuffle(1, 0)], [0]); // One clip: it can only follow itself
});

test("bedLevel: the level for each state of the show", () => {
    const { sandbox } = load();
    const level = (state, receiverOn = false, settings = BED_SETTINGS) => sandbox.bedLevel(state, settings, receiverOn);
    assert.equal(level("on air"), 0.05);
    for (const state of ["thinking", "listening", "hearing"]) assert.equal(level(state), 0.15);
    assert.equal(level("recording"), 0);
    for (const state of ["idle", "stopped", "error"]) assert.equal(level(state), null);
    assert.equal(level("listening", true), 0.15); // The receiver on does not matter without off_in_contact
    const offInContact = { ...BED_SETTINGS, off_in_contact: true };
    assert.equal(level("listening", true, offInContact), 0);
    assert.equal(level("on air", true, offInContact), 0);
    assert.equal(level("on air", false, offInContact), 0.05);
    assert.equal(level("stopped", true, offInContact), null);
});

/* ==========================================================================
   The wiring
   ========================================================================== */

test("no bed in the start reply, or no voice: no sound and nothing wired", () => {
    const page = load();
    page.sandbox.unlockAudio();
    page.get("show").run = { run_id: "run-1", bed: null };
    page.sandbox.setState("thinking");
    assert.equal(page.audios.length, 0);
    assert.equal(page.contexts[0].gains.length, 0);

    const silent = load(); // ?voice=off: the page never unlocks its audio
    silent.get("show").run = { run_id: "run-1", bed: { ...BED_SETTINGS, clips: [{ file: "1-a.mp3", gain: 1 }] } };
    silent.sandbox.setState("thinking");
    assert.equal(silent.audios.length, 0);
});

test("the first state of a run wires the bed: the element, its gain, the bed's gain in mono, the mute, the speakers",
    () => {
        const page = load();
        startRun(page, ["1-a b.mp3"]);
        page.sandbox.setState("thinking");

        const ctx = page.contexts[0];
        const { clip, layer, fading, gate, sounds, highpass, lowpass } = gains(page);
        assert.equal(page.audios.length, 1);
        const audio = page.audios[0];
        assert.equal(ctx.elementSources.length, 1);
        assert.equal(ctx.elementSources[0].element, audio);
        assert.deepEqual(ctx.elementSources[0].connected, [clip]);
        assert.deepEqual(clip.connected, [layer]);
        assert.deepEqual(layer.connected, [fading]); // The filter off: straight on to the fading
        assert.deepEqual(fading.connected, [gate]);
        assert.deepEqual(gate.connected, [sounds]);
        assert.deepEqual(sounds.connected, [ctx.destination]);
        assert.deepEqual(highpass.connected, [lowpass]);
        assert.deepEqual(lowpass.connected, [fading]);
        assert.equal(layer.channelCount, 1);
        assert.equal(layer.channelCountMode, "explicit");
        assert.equal(layer.channelInterpretation, "speakers");
        assert.equal(audio.src, "/api/show/bed/1-a%20b.mp3");
        assert.deepEqual(audio.plays, ["/api/show/bed/1-a%20b.mp3"]);
        assert.deepEqual(clip.gain.lastRamp(), ["ramp", 1, 10 + page.get("BED.clipFadeS")]);
    });

test("the gauge never hears the bed: no buffer source, nothing through the voice's tap", () => {
    const page = load({ withGauge: true });
    startRun(page);
    page.sandbox.setState("thinking");
    assert.equal(page.contexts[0].bufferSources, 0);
    assert.equal(page.audios.length, 1);
});

/* ==========================================================================
   The levels
   ========================================================================== */

test("the level follows the show: up between rounds, down under a round, silent while the listener holds to talk",
    () => {
        const page = load();
        startRun(page);
        const { sandbox } = page;
        sandbox.setState("thinking");
        const { layer } = gains(page);
        assert.deepEqual(layer.gain.lastRamp(), ["ramp", 0.15, 10 + 1.5]); // From silence, over rise_s

        sandbox.setState("on air");
        assert.deepEqual(layer.gain.lastRamp(), ["ramp", 0.05, 10 + 0.5]); // Down, over dip_s

        sandbox.setState("listening", "10 s");
        assert.deepEqual(layer.gain.lastRamp(), ["ramp", 0.15, 10 + 1.5]);
        const calls = layer.gain.calls.length;
        sandbox.setState("listening", "9 s"); // The countdown asks for the same level: nothing moves
        assert.equal(layer.gain.calls.length, calls);

        sandbox.setState("recording", "30 s");
        assert.deepEqual(layer.gain.lastRamp(), ["ramp", 0, 10 + page.get("BED.silenceS")]);

        sandbox.setState("hearing");
        assert.deepEqual(layer.gain.lastRamp(), ["ramp", 0.15, 10 + 1.5]);
        assert.equal(page.audios[0].plays.length, 1); // One clip, playing on through every state
    });

test("off_in_contact: silent while the receiver is on, back when it goes off", () => {
    const page = load();
    startRun(page, undefined, { off_in_contact: true });
    const { sandbox } = page;
    sandbox.setState("on air");
    const { layer } = gains(page);
    assert.equal(layer.gain.target(), 0.05);

    sandbox.setReceiver(true);
    assert.equal(layer.gain.target(), 0);
    sandbox.setState("listening", "10 s");
    assert.equal(layer.gain.target(), 0);

    sandbox.setReceiver(false);
    assert.equal(layer.gain.target(), 0.15);
});

test("Stop pauses the bed at once; Resume picks the same clip up where it stopped, rising from silence", () => {
    const page = load();
    startRun(page);
    const { sandbox } = page;
    sandbox.setState("on air");
    const audio = page.audios[0];
    const clipSrc = audio.src;

    sandbox.setState("stopped");
    const { layer } = gains(page);
    assert.equal(audio.paused, true);
    assert.equal(layer.gain.target(), 0);
    assert.equal(layer.gain.lastRamp()[1], 0.05); // No ramp to 0: set at once

    sandbox.setState("thinking");
    assert.equal(audio.paused, false);
    assert.equal(audio.src, clipSrc);
    assert.deepEqual(audio.plays, [clipSrc, clipSrc]);
    assert.deepEqual(layer.gain.lastRamp(), ["ramp", 0.15, 10 + 1.5]);

    sandbox.setState("error", "the round failed");
    assert.equal(audio.paused, true);
});

/* ==========================================================================
   The clips
   ========================================================================== */

test("a clip that ends gives way to the next; a used-up pass is reshuffled, never repeating across the seam", () => {
    const page = load();
    startRun(page, ["1-a.mp3", "2-b.mp3"]);
    page.sandbox.setState("thinking");
    const audio = page.audios[0];
    const heard = [audio.src];
    for (let i = 0; i < 7; i++) {
        audio.fire("ended");
        heard.push(audio.src);
    }
    for (let i = 1; i < heard.length; i++) assert.notEqual(heard[i], heard[i - 1], `clip ${i} repeats`);
    for (let pass = 0; pass < heard.length; pass += 2) {
        assert.deepEqual(new Set(heard.slice(pass, pass + 2)).size, 2); // Each pass plays both clips
    }
    assert.equal(audio.plays.length, 8);
});

test("a clip that ends while the bed is paused loads the next without playing it", () => {
    const page = load();
    startRun(page);
    page.sandbox.setState("thinking");
    const audio = page.audios[0];
    page.sandbox.setState("stopped");
    const before = audio.src;
    audio.fire("ended");
    assert.notEqual(audio.src, before);
    assert.equal(audio.plays.length, 1);
});

test("a clip that fails is skipped; when every clip fails in a row, the bed gives up", () => {
    const page = load();
    startRun(page, ["1-a.mp3", "2-b.mp3", "3-c.mp3"]);
    page.sandbox.setState("thinking");
    const audio = page.audios[0];
    const first = audio.src;
    audio.fire("error");
    assert.notEqual(audio.src, first);
    audio.fire("playing"); // A clip that plays resets the count
    audio.fire("error");
    audio.fire("error");
    assert.equal(page.get("bed.gaveUp"), false);
    audio.fire("error");
    assert.equal(page.get("bed.gaveUp"), true);
    assert.equal(audio.paused, true);
    const plays = audio.plays.length;
    page.sandbox.setState("on air");
    assert.equal(audio.plays.length, plays);
});

test("a new run starts a new pass over its own clips", () => {
    const page = load();
    startRun(page, ["1-a.mp3"]);
    page.sandbox.setState("thinking");
    page.sandbox.setState("stopped");
    startRun(page, ["9-z.mp3"], {}, "run-2");
    page.sandbox.setState("thinking");
    const audio = page.audios[0];
    assert.equal(page.audios.length, 1); // The same element, the same wiring
    assert.equal(audio.src, "/api/show/bed/9-z.mp3");
    assert.equal(audio.paused, false);
});

/* ==========================================================================
   The second build: the silences, the AM filter, the fading
   ========================================================================== */

test("bedBetween and bedFadingTarget: a time in a range, a level within plus or minus some dB", () => {
    const { sandbox } = load();
    assert.equal(sandbox.bedBetween([30, 120], () => 0), 30);
    assert.equal(sandbox.bedBetween([30, 120], () => 0.5), 75);
    assert.equal(sandbox.bedFadingTarget(3, () => 0.5), 1);
    assert.ok(Math.abs(sandbox.bedFadingTarget(3, () => 0) - 10 ** (-3 / 20)) < 1e-9);
    assert.ok(Math.abs(sandbox.bedFadingTarget(3, () => 0.75) - 10 ** (1.5 / 20)) < 1e-9);
});

test("a silence: after silence_every_s the bed fades out, pauses, and after silence_s goes on where it stopped",
    () => {
        const page = load();
        startRun(page, undefined, {}, "run-1", true);
        page.sandbox.setState("thinking");
        const audio = page.audios[0];
        const clipSrc = audio.src;
        const { gate } = gains(page);
        assert.ok(page.timers.pending().includes(75000)); // 30-120 s, the dice at 0.5

        page.timers.fire(75000);
        assert.deepEqual(gate.gain.lastRamp(), ["ramp", 0, 10 + 1]); // Out over silence_fade_s
        assert.equal(page.get("bed.silent"), true);
        assert.equal(audio.paused, false); // Still sounding through the fade
        assert.ok(page.logs.includes("Show: bed silence: 9.0 s")); // 3-15 s, the dice at 0.5

        page.timers.fire(1000);
        assert.equal(audio.paused, true);
        page.sandbox.setState("on air"); // The show goes on through a silence: the level moves, nothing plays
        assert.equal(audio.paused, true);

        page.timers.fire(9000);
        assert.equal(audio.paused, false);
        assert.equal(audio.src, clipSrc); // The same clip, where it stopped
        assert.deepEqual(gate.gain.lastRamp(), ["ramp", 1, 10 + 1]);
        assert.equal(page.get("bed.silent"), false);
        assert.ok(page.timers.pending().includes(75000)); // The next silence is set
    });

test("a clip that ends in a silence's fade loads the next, which waits for the silence's end", () => {
    const page = load();
    startRun(page);
    page.sandbox.setState("thinking");
    const audio = page.audios[0];
    page.timers.fire(75000);
    audio.fire("ended");
    const next = audio.src;
    assert.equal(audio.plays.length, 1);
    page.timers.fire(1000);
    page.timers.fire(9000);
    assert.equal(audio.plays.at(-1), next);
    assert.equal(audio.plays.length, 2);
});

test("Stop in a silence cancels it: Resume comes back with sound and a new silence set", () => {
    const page = load();
    startRun(page);
    page.sandbox.setState("thinking");
    const audio = page.audios[0];
    page.timers.fire(75000);
    page.timers.fire(1000);
    page.sandbox.setState("stopped");
    assert.deepEqual(page.timers.pending(), []);
    assert.equal(gains(page).gate.gain.target(), 1);
    assert.equal(page.get("bed.silent"), false);

    page.sandbox.setState("thinking");
    assert.equal(audio.paused, false);
    assert.ok(page.timers.pending().includes(75000));
});

test("silences off: no silence is ever set", () => {
    const page = load();
    startRun(page, undefined, { silences: false });
    page.sandbox.setState("thinking");
    assert.ok(!page.timers.pending().includes(75000));
});

test("the AM filter: off, the bed goes straight on; the F key routes it through the band, and back", () => {
    const page = load();
    startRun(page, undefined, {}, "run-1", true);
    page.sandbox.setState("thinking");
    const { layer, highpass, lowpass, fading } = gains(page);
    assert.deepEqual(layer.connected, [fading]);
    assert.equal(highpass.type, "highpass");
    assert.equal(lowpass.type, "lowpass");
    assert.equal(highpass.frequency.value, 300);
    assert.equal(lowpass.frequency.value, 3000);
    assert.equal(highpass.Q.value, Math.SQRT1_2);

    page.key("KeyF");
    assert.deepEqual(layer.connected, [highpass]);
    page.key("KeyF");
    assert.deepEqual(layer.connected, [fading]);
    assert.deepEqual(page.logs.slice(-2), ["Show: bed filter on, 300-3000 Hz (F)", "Show: bed filter off (F)"]);
});

test("the AM filter on in the settings: the run starts through the band, at the settings' edges", () => {
    const page = load();
    startRun(page, undefined, { filter: true, filter_low_hz: 400, filter_high_hz: 2500 });
    page.sandbox.setState("thinking");
    const { layer, highpass, lowpass } = gains(page);
    assert.deepEqual(layer.connected, [highpass]);
    assert.equal(highpass.frequency.value, 400);
    assert.equal(lowpass.frequency.value, 2500);
});

test("the F key before the bed plays does nothing", () => {
    const page = load();
    page.key("KeyF");
    startRun(page);
    page.sandbox.setState("thinking");
    assert.deepEqual(gains(page).layer.connected, [gains(page).fading]);
});

test("the fading: every fading_every_s the level glides to a new one within plus or minus fading_db", () => {
    const page = load();
    const dice = [0.5, 0.75]; // The glide's length (4 s of 2-6 s), then its level (+1.5 dB of +/-3 dB)
    let i = 0;
    page.get("bed").random = () => dice[i++ % dice.length];
    startRun(page, undefined, { silences: false });
    page.sandbox.setState("thinking");
    const { fading } = gains(page);
    const [, level, at] = fading.gain.lastRamp();
    assert.ok(Math.abs(level - 10 ** (1.5 / 20)) < 1e-9);
    assert.equal(at, 10 + 4);
    assert.deepEqual(page.timers.pending(), [4000]);

    page.timers.fire(4000);
    assert.equal(fading.gain.calls.filter((c) => c[0] === "ramp").length, 2); // The next glide
    page.sandbox.setState("stopped");
    assert.deepEqual(page.timers.pending(), []);
});

test("the fading off (fading_db 0): the level holds", () => {
    const page = load();
    startRun(page, undefined, { silences: false, fading_db: 0 });
    page.sandbox.setState("thinking");
    assert.equal(gains(page).fading.gain.lastRamp(), null);
    assert.deepEqual(page.timers.pending(), []);
});

/* ==========================================================================
   The M key
   ========================================================================== */

test("the M key mutes the bed and unmutes it, with a short fade; other keys do nothing", () => {
    const page = load();
    startRun(page);
    page.sandbox.setState("thinking");
    const { sounds } = gains(page);
    const fade = page.get("BED.muteFadeS");

    page.key("KeyM");
    assert.deepEqual(sounds.gain.lastRamp(), ["ramp", 0, 10 + fade]);
    page.key("KeyM");
    assert.deepEqual(sounds.gain.lastRamp(), ["ramp", 1, 10 + fade]);

    const calls = sounds.gain.calls.length;
    page.key("KeyM", { repeat: true });
    page.key("KeyM", { metaKey: true });
    page.key("KeyN");
    page.key("Space");
    assert.equal(sounds.gain.calls.length, calls);
});

test("the M key before the bed is wired: the bed starts muted", () => {
    const page = load();
    page.key("KeyM");
    startRun(page);
    page.sandbox.setState("thinking");
    assert.equal(gains(page).sounds.gain.value, 0);
});

/* ==========================================================================
   The console, with debug on
   ========================================================================== */

test("bedDb: a gain as signed dB, one decimal", () => {
    const { sandbox } = load();
    assert.equal(sandbox.bedDb(1), "+0.0 dB");
    assert.equal(sandbox.bedDb(2.9521), "+9.4 dB");
    assert.equal(sandbox.bedDb(0.5), "-6.0 dB");
});

test("with debug on, the console says each clip as it starts, each new shuffle, and the M key", () => {
    const page = load();
    startRun(page, ["1-a.mp3", "2-b.mp3"], {}, "run-1", true);
    page.get("show").run.bed.clips[1].gain = 2.9521;
    page.sandbox.setState("thinking");
    const audio = page.audios[0];
    const fileOf = () => decodeURIComponent(audio.src.split("/").pop());
    const first = fileOf();
    audio.fire("ended");
    const second = fileOf();
    audio.fire("ended");
    const third = fileOf();
    page.key("KeyM");
    page.key("KeyM");

    const gainOf = (file) => (file === "2-b.mp3" ? "+9.4 dB" : "+0.0 dB");
    assert.deepEqual(page.logs, [
        "Show: bed shuffled: a new pass of 2 clips",
        `Show: bed clip 1 of 2: ${first} (gain ${gainOf(first)})`,
        `Show: bed clip 2 of 2: ${second} (gain ${gainOf(second)})`,
        "Show: bed shuffled: a new pass of 2 clips",
        `Show: bed clip 1 of 2: ${third} (gain ${gainOf(third)})`,
        "Show: bed muted (M)",
        "Show: bed unmuted (M)",
    ]);
});

test("with debug off, the bed says nothing in the console", () => {
    const page = load();
    startRun(page);
    page.sandbox.setState("thinking");
    page.audios[0].fire("ended");
    page.key("KeyM");
    assert.deepEqual(page.logs, []);
});

/* ==========================================================================
   The plain page
   ========================================================================== */

test("the plain page's scripts alone define no bed and keep their own functions", () => {
    const page = load({ withBed: false });
    assert.equal(page.get("typeof bedFollow"), "undefined");
    assert.equal(page.get("typeof bed"), "undefined");
    assert.match(page.get("setState.toString()"), /^function setState/);
    assert.match(page.get("setReceiver.toString()"), /^function setReceiver/);
});
