/**
 * old-radio — lays the photograph of the set into the stage twice: once under everything, and once over the
 * transcript cut to the set's magic eye, so lines scroll behind it; and adds the photograph's credit.
 */

const PHOTO_CREDIT = {
    text: "Photo: Philips Sirius BD 400 A (1950), by Bin im Garten, CC BY-SA 3.0, via Wikimedia Commons",
    href: "https://commons.wikimedia.org/wiki/File:Deutsches_Rundfunk-Museum_Ausstellung_auf_der_IFA_2012_PD_02_"
        + "Radioempf%C3%A4nger_Philips_Sirius_BD_400_A,_1950.JPG",
};

/** A frame holding the photo, cropped to the stage. */
function photoFrame(className) {
    const frame = document.createElement("div");
    frame.className = className;
    const photo = document.createElement("div");
    photo.className = "photo";
    frame.appendChild(photo);
    return frame;
}

document.addEventListener("DOMContentLoaded", () => {
    const show = document.getElementById("show");
    show.prepend(photoFrame("photo-frame"));
    document.getElementById("script").after(photoFrame("eye-frame"));

    const credit = document.createElement("div");
    credit.className = "credit";
    const link = document.createElement("a");
    link.href = PHOTO_CREDIT.href;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = PHOTO_CREDIT.text;
    credit.appendChild(link);
    document.body.appendChild(credit);
});
