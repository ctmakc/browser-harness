# Google Cloud OAuth Clients

Use this with `browser-harness` when adding an OAuth redirect URI in a logged-in Chrome profile.

- Client list URL pattern: `https://console.cloud.google.com/auth/clients?project=<project-id>`
- Client edit URL pattern: `https://console.cloud.google.com/auth/clients/<oauth-client-id>?project=<project-id>`
- In the edit form, use `Add URI` under `Authorized redirect URIs`.
- Fill the exact callback URI, then use `Save`.
- Verify after save by checking visible `input` values for the callback URI.

Do not record client secrets, cookies, tokens, or private project credentials in this file.
