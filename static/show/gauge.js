/**
 * gauge.js — The designs' gauge: how loud the show is, from 0 to 1, about sixty times a second.
 *
 * Loaded only by the designed page (templates/show_design.html), after the page's own scripts, which it does
 * not edit: it wraps three of their functions from outside. unlockAudio (player.js) creates the page's
 * AudioContext on the first click; the wrap then taps that context, so every clip the voice plays also feeds an
 * analyser. openMic and closeMic (mic.js) open and close the microphone; the wrap feeds a second analyser from
 * the open microphone, never to the speakers. While the listener records, the gauge follows the microphone;
 * otherwise, the voice.
 *
 * Each frame the level is published as CSS variables on the page's root — --level (the gauge), --level-voice
 * and --level-mic — and handed to the functions registered with onGaugeLevel (a design that redraws, like a
 * scope's trace). The plain page never loads this file.
 *
 * A classic script sharing globals, like the page's own.
 */

const GAUGE = {
    fftSize: 1024,      // samples read per frame
    gain: 3.5,          // speech rarely passes an RMS of 0.3; this spreads it over 0-1
    attack: 0.5,        // how fast the level rises toward a louder frame (0-1)
    release: 0.08,      // how fast it falls back (0-1): a needle's slow return
};

const gauge = {
    ctx: null,          // the page's AudioContext, once tapped
    voice: null,        // the analyser the voice's clips feed
    mic: null,          // the analyser the open microphone feeds
    micSource: null,    // the microphone's source node, while it is open
    buffer: null,       // one frame of samples
    voiceLevel: 0,
    micLevel: 0,
    level: 0,
    listeners: [],      // functions called each frame with the levels
    running: false,
};

/** The root-mean-square of a frame of samples (-1 to 1): its loudness. */
function rmsLevel(samples) {
    let sum = 0;
    for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
    return samples.length ? Math.sqrt(sum / samples.length) : 0;
}

/** Move a level toward a frame's reading: quickly up, slowly down, as a needle does. */
function smoothLevel(previous, target) {
    const rate = target > previous ? GAUGE.attack : GAUGE.release;
    return previous + (target - previous) * rate;
}

/** An analyser's reading this frame, 0-1 (0 without an analyser). */
function readLevel(analyser) {
    if (!analyser) return 0;
    if (!gauge.buffer || gauge.buffer.length !== analyser.fftSize) gauge.buffer = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(gauge.buffer);
    return Math.min(1, rmsLevel(gauge.buffer) * GAUGE.gain);
}

/** Tap an AudioContext: every buffer source it creates also feeds the voice's analyser when played. */
function tapContext(ctx) {
    if (!ctx || gauge.ctx === ctx) return;
    gauge.ctx = ctx;
    gauge.voice = ctx.createAnalyser();
    gauge.voice.fftSize = GAUGE.fftSize;
    const create = ctx.createBufferSource.bind(ctx);
    ctx.createBufferSource = (...args) => {
        const source = create(...args);
        const connect = source.connect.bind(source);
        source.connect = (node, ...rest) => {
            if (node === ctx.destination) connect(gauge.voice);
            return connect(node, ...rest);
        };
        return source;
    };
    startGauge();
}

/** Feed the microphone's analyser from an open stream (never to the speakers). */
function tapMic(stream) {
    if (!gauge.ctx || !stream) return;
    untapMic();
    gauge.micSource = gauge.ctx.createMediaStreamSource(stream);
    gauge.mic = gauge.ctx.createAnalyser();
    gauge.mic.fftSize = GAUGE.fftSize;
    gauge.micSource.connect(gauge.mic);
}

/** Stop listening to the microphone. */
function untapMic() {
    if (gauge.micSource) gauge.micSource.disconnect();
    gauge.micSource = null;
    gauge.mic = null;
    gauge.micLevel = 0;
}

/** Register a function called each frame with {level, voice, mic}. */
function onGaugeLevel(listener) {
    gauge.listeners.push(listener);
}

/** One frame: read both analysers, smooth, pick the gauge's source, publish. */
function gaugeTick() {
    gauge.voiceLevel = smoothLevel(gauge.voiceLevel, readLevel(gauge.voice));
    gauge.micLevel = smoothLevel(gauge.micLevel, readLevel(gauge.mic));
    const recording = typeof show !== "undefined" && show.state === "recording";
    gauge.level = recording ? gauge.micLevel : gauge.voiceLevel;
    const root = globalThis.document && document.documentElement;
    if (root && root.style) {
        root.style.setProperty("--level", gauge.level.toFixed(3));
        root.style.setProperty("--level-voice", gauge.voiceLevel.toFixed(3));
        root.style.setProperty("--level-mic", gauge.micLevel.toFixed(3));
    }
    const levels = { level: gauge.level, voice: gauge.voiceLevel, mic: gauge.micLevel };
    for (const listener of gauge.listeners) listener(levels);
}

/** Run gaugeTick every animation frame (where the browser gives frames). */
function startGauge() {
    if (gauge.running || typeof globalThis.requestAnimationFrame !== "function") return;
    gauge.running = true;
    const frame = () => {
        gaugeTick();
        globalThis.requestAnimationFrame(frame);
    };
    globalThis.requestAnimationFrame(frame);
}

/* The wraps: the page's functions, called as before, then tapped. */

const pageUnlockAudio = unlockAudio;
unlockAudio = function (...args) {
    const result = pageUnlockAudio.apply(this, args);
    tapContext(voice.ctx);
    return result;
};

const pageOpenMic = openMic;
openMic = async function (...args) {
    const opened = await pageOpenMic.apply(this, args);
    if (opened) tapMic(mic.stream);
    return opened;
};

const pageCloseMic = closeMic;
closeMic = function (...args) {
    untapMic();
    return pageCloseMic.apply(this, args);
};
