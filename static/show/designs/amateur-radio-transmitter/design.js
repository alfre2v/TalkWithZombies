/**
 * amateur-radio-transmitter — adds the oscilloscope's trace, two needle meters and the desk microphone to the
 * panel. The trace is the gauge: each frame (gauge.js) it is redrawn as a wave whose height follows the level,
 * with the previous frames fading behind it like a phosphor's afterglow. The PLATE meter follows the voices
 * (--level-voice), the SIGNAL meter the listener's microphone (--level-mic), both in CSS.
 */

const SCOPE_POINTS = 160;
const SCOPE_IDLE = 0.04;       // a faint ripple when all is quiet: the scope is on
const SCOPE_SPEED = 0.18;      // how far the wave moves along each frame
const SCOPE_GLOWS = 3;         // the traces fading behind the current one

/** The trace's path across the scope: a wave of the given height (0-1), shifted along by the phase. */
function scopePath(height, phase) {
    const points = [];
    for (let i = 0; i <= SCOPE_POINTS; i++) {
        const x = (i / SCOPE_POINTS) * 1000;
        const y = 35 - height * 28 * Math.sin(i * 0.45 + phase) * Math.sin(i * 0.07 + phase * 0.3 + 0.6);
        points.push(`${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`);
    }
    return points.join(" ");
}

document.addEventListener("DOMContentLoaded", () => {
    const show = document.getElementById("show");

    const trace = document.createElement("div");
    trace.className = "scope-trace";
    const glows = Array.from({ length: SCOPE_GLOWS }, (_, i) =>
        `<path class="glow" d="${scopePath(0, 0)}" opacity="${(0.12 * (SCOPE_GLOWS - i)).toFixed(2)}"/>`);
    trace.innerHTML = `<svg viewBox="0 0 1000 70" preserveAspectRatio="none" fill="none" stroke="#7dff9a">
        ${glows.join("")}<path class="beam" d="${scopePath(SCOPE_IDLE, 0)}" stroke-width="3"/></svg>`;

    const meters = document.createElement("div");
    meters.className = "meters";
    meters.innerHTML = `
        <div class="meter plate"><div class="needle"></div><div class="caption">PLATE mA</div></div>
        <div class="meter signal"><div class="needle"></div><div class="caption">SIGNAL</div></div>`;

    const mic = document.createElement("div");
    mic.className = "desk-mic";
    mic.innerHTML = `<svg viewBox="0 0 120 150" aria-hidden="true">
        <defs><linearGradient id="chrome" x1="0" x2="1"><stop offset="0" stop-color="#8a8f95"/>
            <stop offset="0.45" stop-color="#f2f4f6"/><stop offset="1" stop-color="#6d7277"/></linearGradient></defs>
        <rect x="20" y="130" width="80" height="14" rx="7" fill="url(#chrome)"/>
        <rect x="56" y="78" width="8" height="54" fill="url(#chrome)"/>
        <rect x="30" y="8" width="60" height="78" rx="30" fill="url(#chrome)" stroke="#444" stroke-width="2"/>
        <g stroke="#555" stroke-width="2">${[22, 32, 42, 52, 62, 72].map((y) =>
            `<line x1="36" y1="${y}" x2="84" y2="${y}"/>`).join("")}</g></svg>`;

    show.append(trace, meters, mic);

    const beam = trace.querySelector(".beam");
    const afterglow = Array.from(trace.querySelectorAll(".glow"));
    const recent = [];
    let phase = 0;
    onGaugeLevel(({ level }) => {
        phase += SCOPE_SPEED;
        const path = scopePath(Math.max(SCOPE_IDLE, level), phase);
        recent.unshift(path);
        recent.length = Math.min(recent.length, SCOPE_GLOWS + 1);
        beam.setAttribute("d", path);
        afterglow.forEach((glow, i) => { if (recent[i + 1]) glow.setAttribute("d", recent[i + 1]); });
    });
});
