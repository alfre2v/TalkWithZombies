/**
 * test_show_ambience.js — Tests for the ambience (static/show/ambience.js): the world outside, under the show.
 *
 * Run with plain Node (Node 20+, no npm packages, no network):
 *
 *     node tests/test_show_ambience.js
 *
 * What it locks in:
 *   - the rules: the level for each state of the show, and a spot's pick (never the spot heard last);
 *   - the wiring: nothing without an ambience in the start reply; with one, two <audio> elements — the textures
 *     through their gain and the silences' gate, the spots through theirs — into the ambience's level (mono), then
 *     the fading, the A key's mute and the speakers, never through the bed's mute;
 *   - the levels following the show: up between rounds, down under a round, silent while the listener holds to
 *     talk, going on while the receiver is on, paused on Stop;
 *   - the spots: one after a random wait in spot_every_s, at its gain times spot_volume, the next set when it
 *     ends, none with spots off;
 *   - the silences on the textures only, a spot still heard in one;
 *   - the keys: A mutes the ambience alone, M the static alone; F flips the AM filter of both, the ambience
 *     following the bed, at the bed's band.
 *   - the sound cues: a round's cue played once, as its first line is heard — a spot at once, cutting one under
 *     way, the random spot's timer set again from its end; a texture in place of the current one, ending a silence,
 *     out of the shuffle's pass, the shuffle going on after it; nothing switched on by a cue (spots off, the A key's
 *     mute), an unknown clip ignored;
 *   - cue-only clips: never in the shuffle or the random spots, played when cued.
 *
 * How it works: as test_show_bed.js — the page's scripts, bed.js and ambience.js evaluated in a fresh vm.Context,
 * with stubs for the AudioContext, its nodes and the <audio> element, recording connections and automation.
 *
 * NOTE: this file is intentionally NOT part of the pytest suite. Run it alongside:
 *     python3 -m pytest
 *     node tests/test_show_ambience.js
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

/** A fresh context with the page's scripts, bed.js and ambience.js. */
function load() {
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
    for (const file of [...PAGE_SCRIPTS, "bed.js", "ambience.js"]) {
        vm.runInContext(fs.readFileSync(path.join(SHOW_DIR, file), "utf8"), sandbox, { filename: file });
    }
    const get = (expression) => vm.runInContext(expression, sandbox);
    const key = (code) => { for (const fn of listeners.keydown || []) fn({ code, repeat: false, preventDefault() {} }); };
    get("bed").random = () => 0.5;
    get("amb").random = () => 0.5; // The dice land in the middle of every range
    return { sandbox, contexts, audios, get, key, logs, timers };
}

const AMBIENCE_SETTINGS = {
    volume_voice: 0.05, volume_between: 0.12, dip_s: 0.8, rise_s: 2.5,
    silences: true, silence_every_s: [45, 150], silence_s: [5, 20], silence_fade_s: 2,
    fading_db: 4, fading_every_s: [5, 15], spots: true, spot_every_s: [20, 60], spot_volume: 1.5,
    filter: false, filter_low_hz: 300, filter_high_hz: 3000,
};
const BED_SETTINGS = {
    volume_voice: 0.05, volume_between: 0.15, dip_s: 0.5, rise_s: 1.5, off_in_contact: false,
    silences: false, silence_every_s: [30, 120], silence_s: [3, 15], silence_fade_s: 1,
    filter: false, filter_low_hz: 300, filter_high_hz: 3000, fading_db: 0, fading_every_s: [2, 6],
};
const CLIPS = [{ file: "dead-1.mp3", gain: 1, kind: "texture" }, { file: "warfare-1.mp3", gain: 1, kind: "texture" },
               { file: "shriek-1.mp3", gain: 0.5, kind: "spot" }, { file: "boom-1.mp3", gain: 2, kind: "spot" }];

/** A run with this ambience (and a bed of one clip, unless withBed is false), as the start reply brings it. */
function startRun(page, { clips = CLIPS, settings = {}, withBed = true, runId = "run-1" } = {}) {
    page.sandbox.unlockAudio();
    page.get("show").run = {
        run_id: runId,
        debug: false,
        bed: withBed ? { ...BED_SETTINGS, clips: [{ file: "hiss.mp3", gain: 1 }] } : null,
        ambience: { ...AMBIENCE_SETTINGS, ...settings, clips },
    };
}

/** The ambience's stages, and its two <audio> elements (the bed's comes first when there is a bed). */
function stages(page) {
    const at = (name) => page.get(`amb.${name}`);
    return { textureGain: at("textureGain"), spotGain: at("spotGain"), gate: at("gate"), layer: at("layer"),
             highpass: at("highpass"), lowpass: at("lowpass"), fading: at("fading"), mute: at("mute"),
             texture: at("texture"), spot: at("spot") };
}

/* ==========================================================================
   The rules
   ========================================================================== */

test("ambLevel: the level for each state of the show", () => {
    const page = load();
    const level = (state) => page.sandbox.ambLevel(state, AMBIENCE_SETTINGS);
    assert.equal(level("idle"), null);
    assert.equal(level("stopped"), null);
    assert.equal(level("thinking"), 0.12);
    assert.equal(level("on air"), 0.05);
    assert.equal(level("listening"), 0.12);
    assert.equal(level("recording"), 0);
    assert.equal(level("hearing"), 0.12);
});

test("ambPickSpot: never the spot heard last, whatever the dice; one spot is always that one", () => {
    const page = load();
    const pick = page.sandbox.ambPickSpot;
    for (const r of [0, 0.3, 0.5, 0.99]) {
        for (let last = 0; last < 4; last++) assert.notEqual(pick(4, last, () => r), last);
        assert.ok(pick(4, null, () => r) < 4);
    }
    assert.equal(pick(1, 0, () => 0.7), 0);
    const seen = new Set([0, 0.26, 0.51, 0.76].map((r) => pick(4, 2, () => r)));
    assert.deepEqual([...seen].sort(), [0, 1, 3]);
});

/* ==========================================================================
   The wiring
   ========================================================================== */

test("no ambience in the start reply: nothing wired for it", () => {
    const page = load();
    page.sandbox.unlockAudio();
    page.get("show").run = { run_id: "run-1", debug: false, bed: null, ambience: null };
    page.sandbox.setState("thinking");
    assert.equal(page.get("amb.ctx"), null);
    assert.equal(page.audios.length, 0);
});

test("the first state of a run wires two elements: textures through the gate, spots around it, to the A mute", () => {
    const page = load();
    startRun(page, { withBed: false });
    page.sandbox.setState("thinking");

    const ctx = page.contexts[0];
    const s = stages(page);
    assert.equal(page.audios.length, 2);
    assert.deepEqual(ctx.elementSources.map((x) => x.element), [s.texture, s.spot]);
    assert.deepEqual(ctx.elementSources[0].connected, [s.textureGain]);
    assert.deepEqual(ctx.elementSources[1].connected, [s.spotGain]);
    assert.deepEqual(s.textureGain.connected, [s.gate]);
    assert.deepEqual(s.gate.connected, [s.layer]);
    assert.deepEqual(s.spotGain.connected, [s.layer]);
    assert.deepEqual(s.layer.connected, [s.fading]); // The filter off: straight on
    assert.deepEqual(s.fading.connected, [s.mute]);
    assert.deepEqual(s.mute.connected, [ctx.destination]);
    assert.equal(s.layer.channelCount, 1);
    assert.equal(s.texture.src, "/api/show/ambience/dead-1.mp3"); // The dice at 0.5 leave two textures in order
    assert.equal(s.texture.plays.length, 1);
    assert.equal(s.spot.plays.length, 0); // A spot waits for its timer
});

test("never through the bed's mute: the M key mutes the static, the A key the ambience", () => {
    const page = load();
    startRun(page);
    page.sandbox.setState("thinking");
    const s = stages(page);
    const bedMute = page.get("bed.sounds");
    assert.notEqual(s.mute, bedMute);

    page.key("KeyM");
    assert.deepEqual(bedMute.gain.lastRamp()[1], 0);
    assert.equal(s.mute.gain.lastRamp(), null);

    page.key("KeyA");
    assert.deepEqual(s.mute.gain.lastRamp()[1], 0);
    page.key("KeyA");
    assert.deepEqual(s.mute.gain.lastRamp()[1], 1);
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
        const { layer } = stages(page);
        assert.deepEqual(layer.gain.lastRamp(), ["ramp", 0.12, 10 + 2.5]);
        sandbox.setState("on air");
        assert.deepEqual(layer.gain.lastRamp(), ["ramp", 0.05, 10 + 0.8]);
        sandbox.setState("recording", "30 s");
        assert.deepEqual(layer.gain.lastRamp(), ["ramp", 0, 10 + page.get("AMB.silenceS")]);
        sandbox.setState("hearing");
        assert.deepEqual(layer.gain.lastRamp(), ["ramp", 0.12, 10 + 2.5]);
    });

test("the receiver on changes nothing: the world outside goes on through a call", () => {
    const page = load();
    startRun(page);
    page.sandbox.setState("thinking");
    const calls = stages(page).layer.gain.calls.length;
    page.sandbox.setReceiver(true);
    assert.equal(stages(page).layer.gain.calls.length, calls);
});

test("Stop pauses both elements and cancels every timer; Start again resumes the texture where it stopped", () => {
    const page = load();
    startRun(page, { withBed: false });
    page.sandbox.setState("thinking");
    const s = stages(page);
    assert.ok(page.timers.pending().length >= 3); // A silence, a fading, a spot

    page.sandbox.setState("stopped");
    assert.equal(s.texture.paused, true);
    assert.equal(s.spot.paused, true);
    assert.deepEqual(page.timers.pending(), []);

    page.sandbox.setState("thinking");
    assert.equal(s.texture.plays.length, 2);
    assert.equal(s.texture.plays[1], s.texture.plays[0]); // The same texture, picked up
});

/* ==========================================================================
   The spots
   ========================================================================== */

test("a spot after a random wait in spot_every_s, at its gain times spot_volume; the next set when it ends", () => {
    const page = load();
    startRun(page, { withBed: false, settings: { silences: false, fading_db: 0 } });
    page.sandbox.setState("thinking");
    const s = stages(page);
    assert.deepEqual(page.timers.pending(), [40000]); // The middle of [20, 60] s

    page.timers.fire(40000);
    assert.equal(s.spot.plays.length, 1);
    const first = s.spot.src;
    const clip = CLIPS.find((c) => `/api/show/ambience/${c.file}` === first);
    assert.equal(clip.kind, "spot");
    assert.deepEqual(s.spotGain.gain.lastRamp()[1], clip.gain * 1.5);
    assert.deepEqual(page.timers.pending(), []); // None while it plays

    s.spot.fire("ended");
    assert.deepEqual(page.timers.pending(), [40000]);
    page.timers.fire(40000);
    assert.notEqual(s.spot.src, first); // Never the same spot twice in a row
});

test("spots off, or no spot among the clips: no spot is ever set", () => {
    for (const run of [{ settings: { spots: false } }, { clips: CLIPS.filter((c) => c.kind === "texture") }]) {
        const page = load();
        startRun(page, { withBed: false, ...run, settings: { silences: false, fading_db: 0, ...(run.settings || {}) } });
        page.sandbox.setState("thinking");
        assert.deepEqual(page.timers.pending(), []);
    }
});

test("only spots: no texture is loaded, the spots still come", () => {
    const page = load();
    startRun(page, { withBed: false, clips: CLIPS.filter((c) => c.kind === "spot"), settings: { fading_db: 0 } });
    page.sandbox.setState("thinking");
    const s = stages(page);
    assert.equal(s.texture.plays.length, 0);
    assert.deepEqual(page.timers.pending(), [40000]);
    page.timers.fire(40000);
    assert.equal(s.spot.plays.length, 1);
});

/* ==========================================================================
   The silences, the fading
   ========================================================================== */

test("a silence fades the textures out through the gate and pauses them; a spot still comes through", () => {
    const page = load();
    startRun(page, { withBed: false, settings: { fading_db: 0 } });
    page.sandbox.setState("thinking");
    const s = stages(page);
    assert.deepEqual(page.timers.pending(), [40000, 97500]); // A spot at 40 s, a silence at the middle of [45, 150]

    page.timers.fire(97500);
    assert.deepEqual(s.gate.gain.lastRamp(), ["ramp", 0, 10 + 2]);
    page.timers.fire(2000);
    assert.equal(s.texture.paused, true);

    page.timers.fire(40000);
    assert.equal(s.spot.paused, false); // The spot's path bypasses the gate
    page.timers.fire(12500); // The middle of [5, 20] s: the silence ends
    assert.equal(s.texture.paused, false);
    assert.deepEqual(s.gate.gain.lastRamp(), ["ramp", 1, 10 + 2]);
});

test("the fading glides the ambience within plus or minus fading_db every fading_every_s", () => {
    const page = load();
    startRun(page, { withBed: false, settings: { silences: false, spots: false } });
    page.sandbox.setState("thinking");
    const { fading } = stages(page);
    assert.deepEqual(fading.gain.lastRamp(), ["ramp", 1, 10 + 10]); // The dice in the middle: 0 dB, over 10 s
    assert.deepEqual(page.timers.pending(), [10000]);
});

/* ==========================================================================
   The AM filter: the bed's, flipped by F for both
   ========================================================================== */

test("the F key flips the AM filter of the bed and the ambience together, at the bed's band", () => {
    const page = load();
    startRun(page, { settings: { filter_low_hz: 400, filter_high_hz: 2000 } });
    page.sandbox.setState("thinking");
    const s = stages(page);
    assert.deepEqual(s.layer.connected, [s.fading]);

    page.key("KeyF");
    assert.equal(page.get("bed.filterOn"), true);
    assert.equal(page.get("amb.filterOn"), true);
    assert.deepEqual(s.layer.connected, [s.highpass]);
    assert.equal(s.highpass.frequency.value, 400);
    assert.equal(s.lowpass.frequency.value, 2000);

    page.key("KeyF");
    assert.equal(page.get("bed.filterOn"), false);
    assert.equal(page.get("amb.filterOn"), false);
    assert.deepEqual(s.layer.connected, [s.fading]);
});

test("the AM filter on in the settings: the run starts through the band", () => {
    const page = load();
    startRun(page, { withBed: false, settings: { filter: true } });
    page.sandbox.setState("thinking");
    const s = stages(page);
    assert.deepEqual(s.layer.connected, [s.highpass]);
});

/* ==========================================================================
   The sound cues
   ========================================================================== */

/** The round now playing, bringing a cue as show.js keeps it from the round's "cue" event. */
function cueRound(page, file, kind) {
    page.get("show").current = { cue: { type: "cue", file, kind } };
}

test("a cued spot plays once, as the round's first line is heard, cutting a spot under way", () => {
    const page = load();
    startRun(page, { withBed: false });
    page.sandbox.setState("thinking");
    const s = stages(page);
    page.timers.fire(40000); // A random spot: the dice at 0.5 pick the first
    assert.deepEqual(s.spot.plays, ["/api/show/ambience/shriek-1.mp3"]);

    cueRound(page, "boom-1.mp3", "spot");
    page.sandbox.setState("thinking");
    assert.equal(s.spot.plays.length, 1); // Not before the line is heard
    page.sandbox.setState("on air");
    assert.deepEqual(s.spot.plays, ["/api/show/ambience/shriek-1.mp3", "/api/show/ambience/boom-1.mp3"]);
    assert.equal(s.spotGain.gain.target(), 2 * 1.5);
    assert.ok(!page.timers.pending().includes(40000)); // The random spot's timer reset: set again when the cue ends

    page.sandbox.setState("thinking");
    page.sandbox.setState("on air");
    assert.equal(s.spot.plays.length, 2); // Once a round
    s.spot.fire("ended");
    assert.ok(page.timers.pending().includes(40000));
});

test("a cued texture takes the current one's place to its end, ending a silence; the shuffle goes on after it", () => {
    const page = load();
    startRun(page, { withBed: false });
    page.sandbox.setState("thinking");
    const s = stages(page);
    assert.equal(s.texture.src, "/api/show/ambience/dead-1.mp3");
    page.timers.fire(97500); // A silence: the textures fade out, then the texture pauses
    page.timers.fire(2000);
    assert.equal(page.get("amb.silent"), true);
    assert.ok(page.timers.pending().includes(12500));

    cueRound(page, "warfare-1.mp3", "texture");
    page.sandbox.setState("on air");
    assert.equal(page.get("amb.silent"), false);
    assert.equal(s.gate.gain.target(), 1);
    assert.equal(s.texture.src, "/api/show/ambience/warfare-1.mp3");
    assert.equal(s.texture.plays.at(-1), "/api/show/ambience/warfare-1.mp3");
    assert.ok(!page.timers.pending().includes(12500)); // The silence's end cancelled
    assert.ok(page.timers.pending().includes(97500)); // The next silence set from now
    assert.deepEqual([...page.get("amb.order")], []); // Out of this pass of the shuffle

    s.texture.fire("ended");
    assert.notEqual(s.texture.src, "/api/show/ambience/warfare-1.mp3"); // A new pass, never the same across the seam
    assert.equal(s.texture.src, "/api/show/ambience/dead-1.mp3");
});

test("a cue switches nothing on: no spot with spots off, the A key's mute holds, an unknown clip is ignored", () => {
    const page = load();
    startRun(page, { withBed: false, settings: { spots: false } });
    page.sandbox.setState("thinking");
    const s = stages(page);
    cueRound(page, "boom-1.mp3", "spot");
    page.sandbox.setState("on air");
    assert.equal(s.spot.plays.length, 0);

    page.key("KeyA");
    page.sandbox.setState("thinking");
    cueRound(page, "warfare-1.mp3", "texture");
    page.sandbox.setState("on air");
    assert.equal(s.texture.src, "/api/show/ambience/warfare-1.mp3");
    assert.equal(s.mute.gain.target(), 0);

    page.sandbox.setState("thinking");
    cueRound(page, "nope.mp3", "texture");
    page.sandbox.setState("on air");
    assert.equal(s.texture.src, "/api/show/ambience/warfare-1.mp3");
});

/* ==========================================================================
   Cue-only clips
   ========================================================================== */

test("ambRotation: the clips of a kind in the random rotation, all but the cue-only ones", () => {
    const page = load();
    const clips = [{ file: "a.mp3", kind: "spot" }, { file: "b.mp3", kind: "spot", cue_only: true },
                   { file: "c.mp3", kind: "texture", cue_only: false }];
    assert.deepEqual(page.sandbox.ambRotation(clips, "spot").map((c) => c.file), ["a.mp3"]);
    assert.deepEqual(page.sandbox.ambRotation(clips, "texture").map((c) => c.file), ["c.mp3"]);
});

test("a cue-only spot never comes at random, and plays on its cue", () => {
    const page = load();
    const clips = CLIPS.map((c) => (c.file === "boom-1.mp3" ? { ...c, cue_only: true } : c));
    startRun(page, { withBed: false, clips });
    page.sandbox.setState("thinking");
    const s = stages(page);
    for (let i = 0; i < 3; i++) {
        page.timers.fire(40000);
        s.spot.fire("ended");
    }
    assert.deepEqual([...new Set(s.spot.plays)], ["/api/show/ambience/shriek-1.mp3"]);

    cueRound(page, "boom-1.mp3", "spot");
    page.sandbox.setState("on air");
    assert.equal(s.spot.plays.at(-1), "/api/show/ambience/boom-1.mp3");
});

test("a cue-only texture never comes in the shuffle, plays on its cue to its end, then the shuffle goes on", () => {
    const page = load();
    const clips = CLIPS.map((c) => (c.file === "warfare-1.mp3" ? { ...c, cue_only: true } : c));
    startRun(page, { withBed: false, clips });
    page.sandbox.setState("thinking");
    const s = stages(page);
    for (let i = 0; i < 3; i++) s.texture.fire("ended");
    assert.deepEqual([...new Set(s.texture.plays)], ["/api/show/ambience/dead-1.mp3"]);

    cueRound(page, "warfare-1.mp3", "texture");
    page.sandbox.setState("on air");
    assert.equal(s.texture.src, "/api/show/ambience/warfare-1.mp3");
    s.texture.fire("ended");
    assert.equal(s.texture.src, "/api/show/ambience/dead-1.mp3");
});
