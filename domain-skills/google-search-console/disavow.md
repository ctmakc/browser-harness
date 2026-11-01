# Search Console — Disavow tool (no API)

URL: `https://search.google.com/search-console/disavow-links?resource_id=<url-encoded URL-prefix property>`
(works for URL-prefix properties only, e.g. `https%3A%2F%2Flegal.ua%2F`). Page text shows
`N доменов и M URL отклонены` + `Загружен <file> (<time>)`, buttons «Заменить», «Скачать список».

## Trap: background agent tab = inert UI (01.11.2026)
The agent tab in the owner's Chrome is hidden (`document.visibilityState === 'hidden'`), so
`requestAnimationFrame` never fires. Search Console (Wiz/Material buttons) runs click handling and
re-render through rAF: clicks fire analytics but nothing visible happens, the page text never updates,
`Page.captureScreenshot` hangs 60 s.
- The upload itself DOES go through: `upload_file("input[type=file]", path)` on the hidden
  `<input type=file jsaction="change:…">` replaced the list immediately (seen only after reload).
  Do not repeat it "because nothing changed".
- To see state / use buttons: `cdp("Page.addScriptToEvaluateOnNewDocument", source=<shim>)` where the
  shim replaces rAF with `setTimeout(cb,16)` and defines `document.visibilityState='visible'`,
  `document.hidden=false`; then `open_url(url, reload=True)` once. Remove it at the end with
  `Page.removeScriptToEvaluateOnNewDocument`.
- «Скачать список» builds the file in page memory (`new Blob([...])`) without an `<a download>` the
  `download()` hook can catch: wrap `window.Blob` before clicking and read the joined parts.
- Google REPLACES the whole list on upload: always upload a merged file (old list + new domains).
