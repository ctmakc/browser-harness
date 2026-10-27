# Kaggle: hackathon / paper-track Writeup

## Map
- List: `/competitions/<slug>/writeups`. "New Writeup" creates a draft at once (`/writeups/new-writeup-<ms>`); the editor opens as a full-page "Create Writeup" layer over the list.
- After the first Save Draft the URL becomes `/writeups/<slug-of-title, truncated ~48 chars>`; the view page has Edit / Submit at the top and a "N/6 Complete" banner.
- Fields: `input[name=title]` (80 chars max), `input[name=subtitle]` (140), card image (min 560x280, crop dialog for cover and a square thumbnail), Media gallery (optional), `textarea[aria-label="Project Description"]` (plain markdown textarea), Project links ("Add a link" sheet: `input[name=url]`, `input[placeholder="Title *"]`, `input[name=description]`, button Insert), Files (Upload Files, 100 MB), DOI checkbox.
- Checklist (info icon): Title, Subtitle, Card and Thumbnail Image, Submission Track (auto), Project Description, **Project Links**. An uploaded file does not satisfy Project Links; at least one link is required.

## Mechanics
- All text inputs are React-controlled: native value setter + `input` event works; the word counter under the description updates.
- File pickers (description "... > Upload image", card "Browse Files", "Upload Files"): enable `Page.setInterceptFileChooserDialog` on your session, click, wait for `Page.fileChooserOpened` in `drain_events()`, then `DOM.setFileInputFiles(backendNodeId=...)`. No native dialog opens in the owner's Chrome. The first image upload shows a "Before you upload..." EXIF notice with an OK button that must be clicked first.
- "Upload image" inserts `![](https://www.googleapis.com/download/storage/v1/b/kaggle-user-content/...)` at the cursor; collect those URLs and write the final markdown in one go.
- Save Draft at 100% complete opens "Just checking - would you like to submit?" with its own Save Draft / Submit; the page text behind it is stale.
- Submit on the view page opens "Submit your Writeup?" (CC BY 4.0, public at hackathon close) with Cancel / Submit inside `[role=dialog]`.

## Traps
- Markdown image whose alt text contains `[...]` (e.g. citation tags) renders as "!" plus a link. Keep alt short (`![Figure 1](url)`) and put the caption in a separate paragraph.
- An "Internal error" toast may appear right after Submit while the status is fine; confirm on the list page ("Your Work" card shows "Submitted").
- Screenshots in a hidden background tab stall; use an off-screen window (see `submit-code-competition.md`, section Window).
