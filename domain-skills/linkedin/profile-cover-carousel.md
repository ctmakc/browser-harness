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

