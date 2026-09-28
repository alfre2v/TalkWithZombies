/**
 * field-radio — adds the SIGNAL meter (the gauge: its needle's angle, a still level for now; the sound level will
 * drive it in stage two) and the telephone handset to the set's panel.
 */

document.addEventListener("DOMContentLoaded", () => {
    const meter = document.createElement("div");
    meter.className = "field-meter";
    meter.style.setProperty("--needle", "16deg");
    meter.innerHTML = `<div class="needle"></div><div class="panel-label">Signal</div>`;

    const handset = document.createElement("div");
    handset.className = "handset";
    handset.innerHTML = `<svg viewBox="0 0 200 90" aria-hidden="true">
        <path d="M18 62 C18 30, 50 22, 70 30 L130 30 C150 22, 182 30, 182 62 L160 70 C150 52, 140 50, 128 52
                 L72 52 C60 50, 50 52, 40 70 Z" fill="#1c1c1a" stroke="#000" stroke-width="2"/>
        <ellipse cx="34" cy="66" rx="20" ry="12" fill="#262624" stroke="#000" stroke-width="2"/>
        <ellipse cx="166" cy="66" rx="20" ry="12" fill="#262624" stroke="#000" stroke-width="2"/>
        <rect x="88" y="36" width="24" height="10" rx="3" fill="#6d6d66"/></svg>`;

    document.getElementById("show").append(meter, handset);
});
