# Downloads

Separate browser-triggered downloads from direct `http_get(...)` fetches, and document the minimal signals that prove a download actually started.

## Never call setDownloadBehavior on the owner's Chrome

`Browser.setDownloadBehavior` / `Page.setDownloadBehavior` with **any** behavior (including `default`) makes Chromium install `DevToolsDownloadManagerDelegate` over the profile's download manager for the rest of the Chrome process (`content/browser/devtools/protocol/devtools_download_manager_delegate.{h,cc}`: the constructor calls `download_manager_->SetDelegate(this)`; it overrides only DetermineDownloadTarget, ShouldOpenDownload, GetNextId, GetDownloadByGuid, SupportsHistoryLoading, Shutdown). `OpenDownload` and `ShowDownloadInShell` fall back to the empty base implementations, so "Open" and "Show in folder" in the owner's Chrome silently do nothing until Chrome restarts. With `allow` + `downloadPath` the owner's files also land in the agent's folder (no Save dialog, not shown in the bubble).

Reproduced 02.10.2026 on a fresh Chrome 153 profile: show-in-folder → portal `OpenDirectory` → file manager opens; after one `setDownloadBehavior(default)` the same click produces no D-Bus call and no `xdg-open`.

`daemon.py` rejects both methods when it drives the local owner profile (`BU_NAME=default`, no `BU_CDP_WS`, no remote).

## How to download instead

```python
path = download(lambda: click(640, 420))        # <a download>, blob:, data: links; returns dest_dir/<name>
path = fetch_file("https://site/report.pdf")    # direct URL, page cookies included
```

`download()` installs a page hook (anchor `.click()` patch + capturing click listener) that cancels the native download and fetches the bytes with the page's credentials; works for blobs revoked right after the click. Default dest: `$TMPDIR/bh-downloads/<agent>/`.

Not covered: files the server returns only to a form POST or a top-level navigation. Use the agent Chrome (:9333) for those; changing its download behavior is fine.

## Diagnose

- `grep blocked /tmp/bu-default.log` — agents that tried the forbidden call.
- Owner says "Open / Show in folder does nothing": watch `dbus-monitor --session` for `OpenDirectory` and `inotifywait`-style opens of `/usr/bin/xdg-open` while clicking; silence from Chrome means the DevTools delegate is installed → restart Chrome (ask the owner first).
- `~/.config/google-chrome/Default/History` (copy, sqlite) `downloads.target_path` — a foreign path means an `allow` override.
- `download.open_pdf_in_system_reader: true` in Preferences ("Always open PDFs" from the bubble menu) skips the Save dialog and hands PDFs to xdg-open; reset via `chrome://settings/downloads` → `chrome.send('resetAutoOpenFileTypes')`.
