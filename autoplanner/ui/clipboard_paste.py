"""Paste a screenshot from the clipboard (R68).

A small custom component built on Streamlit's components v2 (no build step, no extra
dependency). The paste box is contenteditable, so every browser fires a real `paste`
event on it, and the image comes from `clipboardData` without any clipboard permission
(Chrome, Edge, Firefox, Brave). Where the async Clipboard API exists, a "Paste from
clipboard" button is offered as well. The browser sends the image once, as a data URL
trigger value; Python decodes it in memory and never stores it (R42).
"""

from __future__ import annotations

import base64
import binascii
import re

import streamlit as st

from autoplanner.config import MAX_UPLOAD_BYTES
from autoplanner.importers.gemini_vision import image_mime

TIP = "Press Windows+Shift+S, select the Assignments list, then click here and press Ctrl+V."
LABEL = "Paste your screenshot here (Ctrl+V)"
DATA_URL = re.compile(r"^data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]+={0,2})$")


class PasteError(ValueError):
    """The pasted content can't be used; the message is shown to the user."""


def decode_pasted(payload) -> bytes:
    """Turn the component's trigger value into image bytes, or raise PasteError."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data_url"), str):
        raise PasteError("The pasted content wasn't an image. Take a screenshot with Windows+Shift+S first.")
    match = DATA_URL.match(payload["data_url"])
    if not match:
        raise PasteError("Paste a PNG, JPEG or WebP screenshot.")
    encoded = match.group(2)
    if len(encoded) * 3 // 4 > MAX_UPLOAD_BYTES + 3:  # cheap check before decoding
        raise PasteError("That image is larger than 10 MB.")
    try:
        image = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise PasteError("The pasted image couldn't be read. Try copying it again.") from None
    if len(image) > MAX_UPLOAD_BYTES:
        raise PasteError("That image is larger than 10 MB.")
    try:
        image_mime(image)  # really an image of an allowed type, not just a label
    except ValueError as exc:
        raise PasteError(str(exc)) from None
    return image


HTML = f"""
<div class="ap-zone" contenteditable="true" spellcheck="false" role="textbox" tabindex="0"
     aria-label="{LABEL}. {TIP}">
  <div class="ap-title" contenteditable="false">📋 {LABEL}</div>
  <div class="ap-tip" contenteditable="false">{TIP}</div>
  <div class="ap-ready" contenteditable="false">Ready: press Ctrl+V</div>
</div>
<div class="ap-row">
  <button class="ap-button" type="button" hidden>Paste from clipboard</button>
  <span class="ap-note"></span>
</div>
<div class="ap-status" role="status" aria-live="polite"></div>
"""

CSS = """
.ap-zone {
  border: 2px dashed var(--st-primary-color, #2563eb);
  border-radius: 10px;
  padding: 18px 16px;
  text-align: center;
  cursor: pointer;
  caret-color: transparent;
  outline: none;
  background: var(--st-secondary-background-color, #f1f5f9);
  color: var(--st-text-color, inherit);
  font-family: inherit;
}
.ap-zone:focus { border-style: solid; box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.25); }
.ap-title { font-weight: 600; font-size: 1.05rem; }
.ap-tip { margin-top: 6px; font-size: 0.9rem; opacity: 0.8; }
.ap-ready { display: none; margin-top: 8px; font-size: 0.9rem; font-weight: 600; color: var(--st-primary-color, #2563eb); }
.ap-zone:focus .ap-ready { display: block; }
.ap-row { margin-top: 8px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.ap-button {
  border: 1px solid var(--st-primary-color, #2563eb); color: var(--st-primary-color, #2563eb);
  background: transparent; border-radius: 8px; padding: 4px 12px; cursor: pointer; font: inherit;
}
.ap-note, .ap-status { font-size: 0.85rem; opacity: 0.85; }
.ap-status { margin-top: 6px; }
"""

JS = """
export default function (component) {
  const { setTriggerValue, parentElement, data } = component;
  const zone = parentElement.querySelector(".ap-zone");
  const status = parentElement.querySelector(".ap-status");
  const button = parentElement.querySelector(".ap-button");
  const note = parentElement.querySelector(".ap-note");
  const maxBytes = (data && data.max_bytes) || 10 * 1024 * 1024;
  const allowed = ["image/png", "image/jpeg", "image/webp"];
  const say = (text) => { status.textContent = text; };

  const send = (blob) => {
    if (!blob) { say("There's no image on the clipboard. Take a screenshot with Windows+Shift+S first."); return; }
    if (!allowed.includes(blob.type)) { say("That isn't a PNG, JPEG or WebP image."); return; }
    if (blob.size > maxBytes) { say("That image is larger than 10 MB."); return; }
    say("Image received: reading it…");
    const reader = new FileReader();
    reader.onload = () => setTriggerValue("pasted", { data_url: reader.result, type: blob.type, size: blob.size });
    reader.onerror = () => say("The image couldn't be read. Try copying it again.");
    reader.readAsDataURL(blob);
  };

  const imageFrom = (items) => {
    for (const item of items || []) {
      if (item.kind === "file" && item.type.startsWith("image/")) return item.getAsFile();
    }
    return null;
  };

  // The browser's paste event: works with Ctrl+V and the context menu, no permission needed.
  const onPaste = (event) => {
    event.preventDefault();
    send(imageFrom(event.clipboardData && event.clipboardData.items));
  };
  const onBeforeInput = (event) => event.preventDefault();  // the box only takes images, never text
  const onDragOver = (event) => event.preventDefault();
  const onDrop = (event) => {
    event.preventDefault();
    const files = event.dataTransfer && event.dataTransfer.files;
    send(files && files.length ? files[0] : null);
  };
  zone.addEventListener("paste", onPaste);
  zone.addEventListener("beforeinput", onBeforeInput);
  zone.addEventListener("dragover", onDragOver);
  zone.addEventListener("drop", onDrop);

  // Optional button: the async Clipboard API, only where the browser has it.
  if (window.isSecureContext && navigator.clipboard && typeof navigator.clipboard.read === "function") {
    button.hidden = false;
    button.onclick = async () => {
      try {
        for (const item of await navigator.clipboard.read()) {
          const type = item.types.find((t) => t.startsWith("image/"));
          if (type) { send(await item.getType(type)); return; }
        }
        say("There's no image on the clipboard. Take a screenshot with Windows+Shift+S first.");
      } catch (err) {
        say("The browser didn't allow reading the clipboard. Click the box above and press Ctrl+V instead.");
      }
    };
  } else {
    note.textContent = "This browser can't read the clipboard from a button: click the box and press Ctrl+V.";
  }

  return () => {
    zone.removeEventListener("paste", onPaste);
    zone.removeEventListener("beforeinput", onBeforeInput);
    zone.removeEventListener("dragover", onDragOver);
    zone.removeEventListener("drop", onDrop);
  };
}
"""

_component = st.components.v2.component("autoplanner_clipboard_paste", html=HTML, css=CSS, js=JS)


def paste_area(key: str) -> dict | None:
    """Show the paste box; returns the pasted payload on the run right after a paste, else None."""
    result = _component(key=key, data={"max_bytes": MAX_UPLOAD_BYTES}, on_pasted_change=lambda: None)
    return getattr(result, "pasted", None) if result is not None else None
