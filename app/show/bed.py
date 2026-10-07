"""The static bed: the clips of radio static the show page plays quietly under the voices.

The clips and their manifest ship with the app in ``Sounds/bed/`` (``get_bed_directory()``), with ``CREDITS.md``
(only CC0 and CC BY clips: the app is MIT): zombie-radio's ``tools/sounds/prepare_bed.py`` copies them there
unchanged and writes ``bed.json``, which names each clip's file and the gain that brings it to a common level
(measured on the mono mix the page plays) — facts about the files, never edited by hand. Which clips play is the
story's decision (its ``bed.yaml``: each clip on or off, with a change of its level by ear); without one, every clip
on disk plays. The start reply hands the page the clips that play and the bed's settings; the page fetches each clip
from ``/api/show/bed/<file>``. A missing or broken manifest means no bed, and a clip the story names but the disk
lacks is skipped; never a failed start: both are logged.

The ambience (the world outside the lab, ``Sounds/ambience/`` with ``ambience.json``, written by zombie-radio's
``tools/sounds/prepare_ambience.py``, and the story's ``ambience.yaml``) is read by the same functions, given its
folder, its manifest and its name; its clips also carry their kind, texture or spot.
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

MANIFEST = "bed.json"
AMBIENCE_MANIFEST = "ambience.json"
KINDS = ("texture", "spot")
# A clip's file name: a plain name in the bed's folder, with an audio extension the page can play
CLIP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.(?:mp3|ogg|opus|wav|m4a)")


def bed_clips(directory: Path, manifest_name: str = MANIFEST, what: str = "The static bed") -> List[dict]:
    """The clips of a manifest that are on disk, each as {"file", "gain"} (and its "kind" when the entry has one);
    [] without a usable manifest. what names the sound in the log: the static bed, or the ambience."""
    manifest = directory / manifest_name
    if not manifest.is_file():
        return []
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))["clips"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("%s's %s cannot be read (%s): no clips", what, manifest, exc)
        return []
    clips = []
    for entry in entries if isinstance(entries, list) else []:
        clip = _clip(directory, entry)
        if clip is None:
            logger.warning("%s skips an entry of %s: %r", what, manifest, entry)
        else:
            clips.append(clip)
    return clips


def _clip(directory: Path, entry) -> Optional[dict]:
    """One manifest entry as {"file", "gain"}, with its "kind" when it has one, or None when its name, gain, kind or
    file is not usable."""
    if not isinstance(entry, dict):
        return None
    name, gain = entry.get("file"), entry.get("gain")
    if not isinstance(name, str) or not CLIP_NAME.fullmatch(name):
        return None
    if isinstance(gain, bool) or not isinstance(gain, (int, float)) or not 0 <= gain <= 100:
        return None
    if "kind" in entry and entry["kind"] not in KINDS:
        return None
    if not (directory / name).is_file():
        return None
    clip = {"file": name, "gain": float(gain)}
    if "kind" in entry:
        clip["kind"] = entry["kind"]
    return clip


def bed_play_list(on_disk: List[dict], chosen, what: str = "The static bed",
                  where: str = "Sounds/bed/bed.json (prepare it with zombie-radio's tools/sounds/prepare_bed.py)"
                  ) -> List[dict]:
    """The clips that play, each as on disk ({"file", "gain"}, and "kind" if it has one): every clip on disk when the
    story chooses none (chosen is None); else the story's enabled clips, in its order, each with its measured gain
    changed by its gain_db. chosen holds the story's clips (app.show.story.BedClip: file, enabled, gain_db); what
    and where name the sound and its manifest in the log."""
    if chosen is None:
        return list(on_disk)
    found = {clip["file"]: clip for clip in on_disk}
    clips = []
    for choice in chosen:
        if not choice.enabled:
            continue
        if choice.file not in found:
            logger.warning("%s skips %s: the story enables it, but %s does not list it", what, choice.file, where)
            continue
        clip = dict(found[choice.file])
        clip["gain"] = round(clip["gain"] * 10 ** (choice.gain_db / 20), 4)
        clips.append(clip)
    return clips


def clip_path(directory: Path, name: str, manifest_name: str = MANIFEST) -> Optional[Path]:
    """The file of a clip the manifest lists and the disk holds, or None: nothing else in the folder is served."""
    if not CLIP_NAME.fullmatch(name):
        return None
    if not any(clip["file"] == name for clip in bed_clips(directory, manifest_name)):
        return None
    return directory / name
