/**
 * old-radio — adds the magic eye to the cabinet. Its opening is the CSS variable --eye-open (degrees of the dark
 * wedge: wide open when quiet, nearly closed when loud); the gauge's sound level will drive it (stage two).
 */

document.addEventListener("DOMContentLoaded", () => {
    const eye = document.createElement("div");
    eye.className = "magic-eye";
    eye.style.setProperty("--eye-open", "38deg");
    const label = document.createElement("div");
    label.className = "magic-eye-label";
    label.textContent = "TUNING";
    document.getElementById("show").append(eye, label);
});
