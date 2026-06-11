# Cloudflare OAuth Consent

Wrangler OAuth opens on `dash.cloudflare.com/oauth2/auth` and redirects through
`/oauth/consent-form?consent_challenge=...`.

Useful flow:

- Start `wrangler login --browser=false` first so the local callback listener is
  active on `http://localhost:8976/oauth/callback`.
- Open the printed OAuth URL in a new tab with `new_tab(url)`.
- If already signed in, the first page shows the account selector and a
  `Review permissions` button.
- The review page shows grouped permission categories and an `Authorize` button.
- After authorization the browser lands on
  `welcome.developers.workers.dev/wrangler-oauth-consent-granted`; the waiting
  Wrangler process should print `Successfully logged in.`

Do not copy OAuth query parameters, tokens, cookies, or callback codes into
docs or commits.
