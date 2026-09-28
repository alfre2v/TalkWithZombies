/**
 * broadcast-studio — adds the clipboard's clip over the script. The VU meters are the cast strip itself, styled:
 * the needle rises on the character speaking now (the page's `speaking` class); stage two can move it with the
 * sound level.
 */

document.addEventListener("DOMContentLoaded", () => {
    const clip = document.createElement("div");
    clip.className = "clipboard-clip";
    document.getElementById("show").append(clip);
});
