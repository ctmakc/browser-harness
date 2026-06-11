# X Replies

Validated against `https://x.com/<handle>/status/<id>` while logged into an existing local Chrome profile.

## Durable selectors

- Main status page keeps the tweet in `article[data-testid="tweet"]`.
- Tweet body text is in `[data-testid="tweetText"]`.
- The inline reply composer on a status page is:
  - textarea: `[data-testid="tweetTextarea_0"]`
  - submit button: `[data-testid="tweetButtonInline"]`
- The public reply counter button on the tweet is `[data-testid="reply"]`.

## Practical workflow

- Open statuses in a **new tab** with `new_tab(url)` so you do not clobber the user's active work.
- On status pages, the inline reply box is often already present without needing to click the reply counter first.
- If the inline box is missing, clicking `[data-testid="reply"]` can surface it.
- Focusing `[data-testid="tweetTextarea_0"]` and then using `type_text(...)` works for drafting a reply.

## Search pages

- Live search URL pattern:
  - `https://x.com/search?q=<urlencoded query>&src=typed_query&f=live`
- Search result tweets can be harvested from `article` nodes by finding `a[href*="/status/"]` inside each article.
- Status timestamps are available via `article.querySelector('time')?.getAttribute('datetime')`.

## Traps

- UI language may be localized, so prefer `data-testid` over visible button text.
- `Ctrl+A` / `Backspace` is not reliably enough by itself to clear the reply box; selecting the reply box contents via DOM range and then sending `Backspace` is more reliable.
- Leave actual posting behind an explicit flag or confirmation. Preparing the draft is stable; auto-submitting should stay opt-in.
