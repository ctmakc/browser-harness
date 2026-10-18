# LinkedIn Profile Cover Carousel

Use a logged-in browser session for profile pages that are blocked to anonymous HTTP fetches.

Profile background carousels render all cover slides as individual `<img>` elements in the DOM, not just the currently visible slide. On a Russian-localized LinkedIn UI, the slide images had alt text equivalent to "main photo as carousel" (`Главное фото в виде карусели`) and URLs under `media.licdn.com/.../profile-displaybackgroundimage-shrink_200_800/...`.

Extraction pattern:

```python
slides = js(r'''
[...document.images].map((img, i) => ({
  i,
  src: img.currentSrc || img.src,
  alt: img.alt,
  w: img.naturalWidth,
  h: img.naturalHeight,
  rect: (() => {
    const r = img.getBoundingClientRect();
    return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)};
  })()
})).filter(x => (x.alt || '').toLowerCase().includes('carousel') || (x.alt || '').includes('карусел'))
''')
```

Download via normal HTTP with a browser user agent and LinkedIn referer. Do not save cookies or signed tokens in notes; media URLs can be short-lived.


## Editing the Premium slideshow (learned 2026-09)

- The banner pencil opens a menu: "edit main image" / "create (or edit) slideshow with Premium". A banner with dots *painted into the image* is a single image — check with `elementFromPoint` over the dots (returns IMG, not buttons).
- The slideshow dialog limits (live UI): PNG/JPEG, **max 3 MB per file**, min 1128×191, up to 5 images. Third-party guides saying 8 MB are outdated for this dialog.
- The dialog has no `input[type=file]` in the main DOM. Use `Page.setInterceptFileChooserDialog(enabled=True)`, click "Upload from computer" (or the `+` under the thumbnails), read `Page.fileChooserOpened` from `drain_events()` (mode `selectMultiple`), then `DOM.setFileInputFiles(files=[...], backendNodeId=...)`. Several files at once land in the chosen order.
- `+` inserts new images *after the selected thumbnail*, not at the end. Hovering a thumbnail shows ← / → arrows to move it one position; the trash deletes the selected one.
- Save takes ~20–40 s for 5 × 2–3 MB; a spinner stays in the modal meanwhile.
- In slideshow mode the page serves only `profile-displaybackgroundimage-shrink_200_800` (800×200 JPEG, no srcset), so sources above 800 px do not reach viewers; a 2× source still downsamples cleanest.
- LinkedIn draws its own dot pill at the bottom-right of the banner (about the right 22% of width, bottom 20% of height). Keep content out of it, and out of the bottom-left avatar area.
- The live slideshow auto-rotates, so clicking a dot may land one slide off. To screenshot a given slide, click its dot, wait ~1.5 s, take two shots ~0.6 s apart and keep the pair that is pixel-identical (the other is mid-swipe).
