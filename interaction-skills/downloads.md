# Downloads

Separate browser-triggered downloads from direct `http_get(...)` fetches, and document the minimal signals that prove a download actually started.

## The trap (25.07.2026, again 01–02.10.2026)

`Browser.setDownloadBehavior` with `behavior: allow|allowAndName` + `downloadPath` changes the download folder of the **whole running Chrome**, for the owner too, until Chrome restarts. Nothing in the UI shows it, and with `allow` Chrome also hides the download from the bubble. The owner saves a PDF, sees nothing, and the file sits in `~/.config/mega-vpn/` or an agent scratchpad. Twice this lasted a full day.

## Rule

1. Browser-triggered download → `download(trigger, dest_dir=None, timeout=120)` from `helpers.py`:

   ```python
   path = download(lambda: click(640, 420))            # or lambda: js("document.querySelector('a.export').click()")
   print(path)                                          # dest_dir/<suggestedFilename>
   ```

   It sets `allowAndName` into `dest_dir` for this one download, waits for `Browser.downloadProgress state=completed` (the daemon tracks it, `meta: downloads`), renames the guid file to the suggested name and **always** restores `default` in `finally`.

2. Plain URL with cookies → no folder change at all: `js("fetch(URL).then(r=>r.blob()).then(b=>new Promise(r=>{const f=new FileReader();f.onload=()=>r(f.result);f.readAsDataURL(b)}))")` → base64 → write locally.

3. Raw `cdp("Browser.setDownloadBehavior", behavior="allow", ...)` in scripts is forbidden. The daemon still catches it: it arms the completion/timer reset and forces `eventsEnabled`.

## Daemon safety net (`daemon.py`)

- On start: `Browser.setDownloadBehavior default` (heals a stale override left by a crashed script or a previous daemon).
- On agent override: reset as soon as the agent's download reaches `completed`/`canceled`; hard ceiling `BU_DL_RESET_SEC` (120 s) after the last override.
- Guard every `BU_DL_GUARD_SEC` (60 s) while no agent holds an override through the daemon — heals direct CDP connections that bypass the daemon.

## Diagnose

- `~/.config/google-chrome/Default/History` (copy it, sqlite): `select datetime(start_time/1000000-11644473600,'unixepoch','localtime'), target_path from downloads order by start_time desc` — a foreign `target_path` is the hijack.
- `grep "download behavior" /tmp/bu-default.log` — who overrode and when it was restored.
- Owner profile has `prompt_for_download: true`: a correct `default` state shows the Save dialog on the owner's screen; a silent save means an override is active.
