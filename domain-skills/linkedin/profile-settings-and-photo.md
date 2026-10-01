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

## Company page admin (/company/<id>/admin/edit/)
- The edit form sets a `beforeunload` guard. `goto()` accepts it automatically now; older code hung `Page.navigate` for 60 s.
- Save once. A second save from the same open form returns "another admin is editing" (version conflict): reload the form, then edit.
- After saving, the form shows a "share your changes" modal. Click "No, thanks".
- Logo: the pencil on the logo opens a native file chooser. Use the same interception trick as for the profile photo.

## Education / intro
- The intro shows exactly two items on the right: one organization and one education entry, picked in /edit/intro/ (`select` elements, set value with the native setter plus a `change` event).
- The school name comes from the linked school page. A school page with a Russian name shows in Russian. To show a custom English name, type free text into the school typeahead, press Escape (don't pick a suggestion), then Save. This unlinks the page logo.
- Edit form URL: /in/<slug>/edit/forms/education/<entryId>/ (entry ids are the option values in the intro select). Several modals in one SPA session can reuse React ids (`_r_4_`), so click by visible coordinates, then check `document.activeElement`.
