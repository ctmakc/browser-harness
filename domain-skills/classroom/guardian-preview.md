# Google Classroom Guardian Preview

Guardian preview URLs look like:

```text
https://classroom.google.com/guar/<course-token>/<student-token>
https://classroom.google.com/u/0/guar/<course-token>/<student-token>?hl=en
```

For extraction, prefer opening a fresh tab with `new_tab(url)` and waiting until `document.body.innerText` contains `Assignment`/`Material` or the localized equivalents. Reusing an existing Classroom tab with `goto(url)` can leave the page in a valid-looking but empty state where only the header and guardian banner render.

The visible guardian preview exposes classwork titles, topics, item type, posted/edited dates, and due dates in the DOM text. It does not expose submitted/missing/graded status in the visible page.

The page uses `ClassroomUi/data/batchexecute` RPCs. Course and user metadata are loaded via `jvsaOd` and `UG41I`; classwork-related RPCs seen during a full load include `gXtzob`, `ZZFlc`, and `dpT4Vd`. These are private UI endpoints, so DOM text extraction from a fresh tab is currently the lower-risk path.
