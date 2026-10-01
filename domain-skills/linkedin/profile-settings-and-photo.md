# LinkedIn: settings URLs and profile photo upload

## Settings, direct routes (no menu clicking needed)
- Followers / "Make follow primary": `https://www.linkedin.com/mypreferences/d/settings/followed`. The page has radio `allowPublicToFollow__ALL_LINKEDIN_USERS` and one checkbox (the toggle). Clicking the hidden `<input>` does nothing: click the visible switch (locate it from a screenshot, to the right of the "make Follow primary" label). Verify with `document.querySelector('input[type=checkbox]').checked`.
- Category pages: `/mypreferences/d/categories/{account|sign-in-and-security|profile-visibility|privacy|ads|notifications}`; every row is an `<a href="/mypreferences/d/settings/...">`. List them with `js` to find the target, so you can skip clicking through menus.

## Profile photo
- Click the avatar on your own profile → "Profile photo" modal: Edit / Update / Frames / Delete + a visibility pill.
- Update → "Upload photo" opens a native file chooser. **No `input[type=file]` exists in the DOM**, so `upload_file()` fails. Use:
  `cdp("Page.enable"); cdp("Page.setInterceptFileChooserDialog", enabled=True)` → click "Upload photo" → find `Page.fileChooserOpened` in `drain_events()` → `cdp("DOM.setFileInputFiles", files=[path], backendNodeId=ev["params"]["backendNodeId"])` → disable the interception.
- Crop dialog → "Save changes". Then reopen the photo modal → visibility pill → choose "Anyone" (default is often "Your network") → Save.
- Do all of this in ONE tab, without reloading the profile between steps.

## Page noise
- `[role=dialog]` also matches 7+ hidden video-caption settings dialogs ("This is a modal window"). Filter by visible text, or use screenshots.
