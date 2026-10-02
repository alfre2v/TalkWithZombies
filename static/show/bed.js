/**
 * bed.js — The static bed: radio static played quietly under the show, from a shuffled list of clips.
 *
 * Loaded by the designed page (templates/show_design.html), and by the plain page only with ?bed=on, after the
 * page's own scripts, which it does not edit: like gauge.js, it wraps two of their functions from outside.
 * setState (show.js) says what the show is doing, and the bed follows it: while a round is said ("on air"), the
 * run's volume_voice; while the page waits — for the next round, for the listener to press, for Whisper —
 * volume_between; while the listener holds push-to-talk ("recording"), silent; on Stop or an error, it pauses,
 * and the next Start or Resume picks it up where it stopped, rising from silence. A dip takes dip_s, a rise
 * rise_s. setReceiver (show.js) says whether the receiver is on: with off_in_contact, the bed is silent while it
 * is. The M key mutes and unmutes it, for the presenter; the audience sees nothing.
 *
 * The run's start reply brings the bed (show.run.bed): its clips — a file served at /api/show/bed/<file> and a
 * gain each, measured to a common level by zombie-radio's tools/sounds/prepare_bed.py — and its settings. No bed in
 * the reply, or no voice (?voice=off), no sound. The clips play in a shuffled order, reshuffled when used up,
 * never the same clip twice across the seam. Each clip streams through an <audio> element into the page's
 * AudioContext, so a long clip is never decoded whole, through a chain of stages:
 *
 *     the clip's gain → the bed's level (mixed down to mono) → the AM filter (or straight on) → the fading
 *     → the silence gate → the mute → the speakers
 *
 * The AM filter (filter, off by default) keeps filter_low_hz to filter_high_hz, the band of a small radio's
 * speaker; the F key flips it live, for an A/B by ear. The fading (QSB): every random time in fading_every_s, the
 * level glides to a new one within plus or minus fading_db. The silences (silences): after a random time in
 * silence_every_s the bed fades out over silence_fade_s and the clip pauses; after a random length in silence_s,
 * the same clip resumes where it stopped and fades back in. The gauge never hears the bed: gauge.js taps only the
 * voice's buffer sources.
 *
 * With the run's debug on, the browser's console says what the bed does: each clip as it starts (its place in the
 * pass, its file, its gain in dB), each new shuffle, each silence, the M key's mute and the F key's filter.
 *
 * A classic script sharing globals, like the page's own.
 */

const BED = {
    silenceS: 0.15,     // how fast the bed goes silent when the listener presses to talk
    clipFadeS: 0.3,     // each clip fades in over this, so a join never clicks in
    muteFadeS: 0.3,     // the M key's fade
    muteKey: "KeyM",
    filterKey: "KeyF",
};

const bed = {
    ctx: null,          // the page's AudioContext, once the bed is wired into it
    sounds: null,       // the gain of every sound but the voice: the M key's mute
    gate: null,         // the silences' gain: 1, or 0 through a silence
    fading: null,       // the fading's gain, gliding around 1
    highpass: null,     // the AM filter's two halves: below filter_low_hz out...
    lowpass: null,      // ...and above filter_high_hz
    layer: null,        // the bed's gain: its level, mixed down to mono
    clipGain: null,     // the clip's own gain, from the start reply
    audio: null,        // the <audio> element that streams the clips
    runId: null,        // the run whose clips are queued
    order: [],          // the clips still to play in this pass, by index
    current: null,      // the clip loaded now, by index
    failures: 0,        // clips that failed to load in a row: when every clip has, the bed gives up
    gaveUp: false,
    playing: false,
    silent: false,      // a silence under way: its fade, its pause
    silenceTimer: null,
    fadingTimer: null,
    filterOn: false,
    receiverOn: false,
    muted: false,
    level: 0,           // the level last asked of the bed's gain
    random: Math.random, // the silences' and the fading's dice (the tests load their own)
};

/* ==========================================================================
   The rules (tested in tests/test_show_bed.js)
   ========================================================================== */

/**
 * A shuffled order of n clips, by index; when n > 1 it never starts with last, the clip that just ended, so the
 * same clip is never heard twice in a row across a reshuffle. random returns a number in [0, 1).
 */
function bedShuffle(n, last, random = Math.random) {
    const order = Array.from({ length: n }, (_, i) => i);
    for (let i = n - 1; i > 0; i--) {
        const j = Math.floor(random() * (i + 1));
        [order[i], order[j]] = [order[j], order[i]];
    }
    if (n > 1 && order[0] === last) {
        const k = 1 + Math.floor(random() * (n - 1));
        [order[0], order[k]] = [order[k], order[0]];
    }
    return order;
}

/**
 * The bed's level for a state of the show (show.js's state names), given the run's bed and whether the receiver
 * is on: null when the bed pauses (the show is not running), 0 when it is silent, else a level from the bed.
 */
function bedLevel(state, settings, receiverOn) {
    if (!RUNNING_STATES.includes(state)) return null;
    if (state === "recording") return 0;
    if (settings.off_in_contact && receiverOn) return 0;
    return state === "on air" ? settings.volume_voice : settings.volume_between;
}

/** A random number of seconds in a [min, max] range. */
function bedBetween(range, random = Math.random) {
    return range[0] + random() * (range[1] - range[0]);
}

/** The fading's next level: a factor within plus or minus db decibels of 1. */
function bedFadingTarget(db, random = Math.random) {
    return 10 ** (((2 * random() - 1) * db) / 20);
}

/* ==========================================================================
   The sound
   ========================================================================== */

/** Move an audio parameter to target over seconds, from wherever it is now (at once when seconds is 0). */
function bedRamp(param, target, seconds) {
    const now = bed.ctx.currentTime;
    param.cancelScheduledValues(now);
    param.setValueAtTime(param.value, now);
    if (seconds > 0) param.linearRampToValueAtTime(target, now + seconds);
    else param.setValueAtTime(target, now);
}

/** Wire the bed into the page's AudioContext, once per context; false when the browser cannot. */
function bedWire() {
    if (bed.ctx === voice.ctx) return true;
    const ctx = voice.ctx;
    if (typeof ctx.createMediaElementSource !== "function" || typeof globalThis.Audio !== "function") return false;
    bed.ctx = ctx;
    bed.sounds = ctx.createGain();
    bed.sounds.gain.value = bed.muted ? 0 : 1;
    bed.sounds.connect(ctx.destination);
    bed.gate = ctx.createGain();
    bed.gate.connect(bed.sounds);
    bed.fading = ctx.createGain();
    bed.fading.connect(bed.gate);
    bed.highpass = ctx.createBiquadFilter();
    bed.highpass.type = "highpass";
    bed.lowpass = ctx.createBiquadFilter();
    bed.lowpass.type = "lowpass";
    for (const filter of [bed.highpass, bed.lowpass]) filter.Q.value = Math.SQRT1_2; // Flat, no peak at the edge
    bed.highpass.connect(bed.lowpass);
    bed.lowpass.connect(bed.fading);
    bed.layer = ctx.createGain();
    bed.layer.channelCount = 1; // A stereo clip is mixed down to mono, (left + right) / 2, as a radio's speaker
    bed.layer.channelCountMode = "explicit";
    bed.layer.channelInterpretation = "speakers";
    bed.layer.gain.value = 0;
    bed.layer.connect(bed.fading);
    bed.clipGain = ctx.createGain();
    bed.clipGain.connect(bed.layer);
    bed.audio = new globalThis.Audio();
    bed.audio.preload = "auto";
    bed.audio.addEventListener("ended", bedNext);
    bed.audio.addEventListener("error", bedFailed);
    bed.audio.addEventListener("playing", () => { bed.failures = 0; });
    ctx.createMediaElementSource(bed.audio).connect(bed.clipGain);
    bed.level = 0;
    return true;
}

/** Route the bed's level through the AM filter, at the run's band, or straight on to the fading. */
function bedRoute() {
    const settings = show.run.bed;
    bed.highpass.frequency.value = settings.filter_low_hz;
    bed.lowpass.frequency.value = settings.filter_high_hz;
    bed.layer.disconnect();
    bed.layer.connect(bed.filterOn ? bed.highpass : bed.fading);
}

/** Follow the show's state: the level it asks for, a pause when it stops. */
function bedFollow() {
    const settings = show.run && show.run.bed;
    if (!settings || !settings.clips.length || !voice.ctx || bed.gaveUp) return;
    const target = bedLevel(show.state, settings, bed.receiverOn);
    if (target === null) {
        bedPause();
        return;
    }
    if (!bedWire()) return;
    if (bed.runId !== show.run.run_id) {
        bed.runId = show.run.run_id;
        bed.order = [];
        bed.current = null;
        bed.filterOn = Boolean(settings.filter);
        bedRoute();
    }
    if (target !== bed.level) {
        let seconds = target < bed.level ? settings.dip_s : settings.rise_s;
        if (show.state === "recording") seconds = BED.silenceS;
        bedRamp(bed.layer.gain, target, seconds);
        bed.level = target;
    }
    if (!bed.playing) {
        bed.playing = true;
        if (bed.current === null) bedNext();
        else bedPlay();
        bedScheduleSilence();
        bedFade();
    }
}

/** Say what the bed does in the browser's console, when the run's debug is on. */
function bedLog(message) {
    if (show.run && show.run.debug) console.info(`Show: bed ${message}`);
}

/** A gain as dB, signed, one decimal: 2.9521 is "+9.4 dB". */
function bedDb(gain) {
    const db = 20 * Math.log10(gain);
    return `${db >= 0 ? "+" : ""}${db.toFixed(1)} dB`;
}

/** Load the next clip of the order (a new shuffle when it is used up), and play it if the bed is playing. */
function bedNext() {
    const clips = show.run.bed.clips;
    if (!bed.order.length) {
        bed.order = bedShuffle(clips.length, bed.current);
        bedLog(`shuffled: a new pass of ${clips.length} clips`);
    }
    bed.current = bed.order.shift();
    const clip = clips[bed.current];
    bedLog(`clip ${clips.length - bed.order.length} of ${clips.length}: ${clip.file} (gain ${bedDb(clip.gain)})`);
    bed.audio.src = `/api/show/bed/${encodeURIComponent(clip.file)}`;
    bed.clipGain.gain.cancelScheduledValues(bed.ctx.currentTime);
    bed.clipGain.gain.setValueAtTime(0, bed.ctx.currentTime);
    bed.clipGain.gain.linearRampToValueAtTime(clip.gain, bed.ctx.currentTime + BED.clipFadeS);
    if (bed.playing && !bed.silent) bedPlay();
}

/** Play the loaded clip from where it is; a refusal is logged, the show goes on. */
function bedPlay() {
    const played = bed.audio.play();
    if (played && typeof played.catch === "function") {
        played.catch((err) => console.warn("Show: the static bed could not play:", err));
    }
}

/** A clip could not be loaded: the next one, unless every clip has failed in a row. */
function bedFailed() {
    bed.failures += 1;
    if (bed.failures >= show.run.bed.clips.length) {
        console.warn("Show: no clip of the static bed would load; the bed is off for this page");
        bed.gaveUp = true;
        bedPause();
        return;
    }
    bedNext();
}

/** Pause the bed at once, keeping its place in the clip; the next level rises from silence, with no silence due. */
function bedPause() {
    bed.playing = false;
    globalThis.clearTimeout(bed.silenceTimer);
    globalThis.clearTimeout(bed.fadingTimer);
    bed.silenceTimer = bed.fadingTimer = null;
    bed.silent = false;
    if (!bed.audio) return;
    bed.audio.pause();
    bedRamp(bed.layer.gain, 0, 0);
    bedRamp(bed.gate.gain, 1, 0);
    bed.level = 0;
}

/* The silences: a timer while the bed plays; a fade out, the clip paused, a fade back in where it stopped. */

/** Set the next silence, a random time in silence_every_s from now (when the run's bed has silences). */
function bedScheduleSilence() {
    const settings = show.run.bed;
    globalThis.clearTimeout(bed.silenceTimer);
    bed.silenceTimer = settings.silences
        ? globalThis.setTimeout(bedSilence, bedBetween(settings.silence_every_s, bed.random) * 1000)
        : null;
}

/** A silence: fade out, then pause the clip for a random length in silence_s. */
function bedSilence() {
    if (!bed.playing) return;
    const settings = show.run.bed;
    const seconds = bedBetween(settings.silence_s, bed.random);
    bed.silent = true;
    bedLog(`silence: ${seconds.toFixed(1)} s`);
    bedRamp(bed.gate.gain, 0, settings.silence_fade_s);
    bed.silenceTimer = globalThis.setTimeout(() => {
        bed.audio.pause();
        bed.silenceTimer = globalThis.setTimeout(bedSilenceEnds, seconds * 1000);
    }, settings.silence_fade_s * 1000);
}

/** The silence is over: the clip goes on where it stopped, fading back in, and the next silence is set. */
function bedSilenceEnds() {
    bed.silent = false;
    bedPlay();
    bedRamp(bed.gate.gain, 1, show.run.bed.silence_fade_s);
    bedScheduleSilence();
}

/** The fading: glide to a new level within plus or minus fading_db, over a random time in fading_every_s. */
function bedFade() {
    const settings = show.run.bed;
    if (!bed.playing || !(settings.fading_db > 0)) return;
    const seconds = bedBetween(settings.fading_every_s, bed.random);
    bedRamp(bed.fading.gain, bedFadingTarget(settings.fading_db, bed.random), seconds);
    bed.fadingTimer = globalThis.setTimeout(bedFade, seconds * 1000);
}

/* The keys: M mutes, F flips the AM filter. */

/** The M key: mute or unmute the bed (and, later, every sound but the voice). */
function bedMute() {
    bed.muted = !bed.muted;
    if (bed.sounds) bedRamp(bed.sounds.gain, bed.muted ? 0 : 1, BED.muteFadeS);
    bedLog(bed.muted ? "muted (M)" : "unmuted (M)");
}

/** The F key: the AM filter on or off, live, for an A/B by ear; nothing before the bed plays. */
function bedFlipFilter() {
    if (!bed.ctx || !show.run || !show.run.bed) return;
    bed.filterOn = !bed.filterOn;
    bedRoute();
    const band = `${show.run.bed.filter_low_hz}-${show.run.bed.filter_high_hz} Hz`;
    bedLog(bed.filterOn ? `filter on, ${band} (F)` : "filter off (F)");
}

/* The wraps: the page's functions, called as before, then followed. */

const pageSetState = setState;
setState = function (...args) {
    const result = pageSetState.apply(this, args);
    bedFollow();
    return result;
};

const pageSetReceiver = setReceiver;
setReceiver = function (on, ...rest) {
    const result = pageSetReceiver.call(this, on, ...rest);
    bed.receiverOn = Boolean(on);
    bedFollow();
    return result;
};

document.addEventListener("keydown", (e) => {
    if (e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.code === BED.muteKey) bedMute();
    else if (e.code === BED.filterKey) bedFlipFilter();
});
