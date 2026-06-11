# Cal.com Settings And API

## Useful Routes

- API keys: `https://app.cal.com/settings/developer/api-keys`
- Event types dashboard: `https://app.cal.com/event-types`
- Public profile: `https://cal.com/{username}`
- Public event type: `https://cal.com/{username}/{slug}`

## API Keys

The API key page has a `New` button that opens a modal. Fill `input#note`, optionally toggle `neverExpires`, then click the `Create` button.

After creation, the key is shown only once in a text input whose value starts with `cal_` / `cal_live_`. Do not print or persist it. Use it immediately from the DOM if needed:

```python
key = js("[...document.querySelectorAll('input')].find(i => i.value && i.value.startsWith('cal_'))?.value")
```

Close the modal with `Done` after finishing so the key is not left visible.

## API V2

Use official API V2 endpoints on `https://api.cal.com/v2` with:

- `Authorization: Bearer <api_key>`
- `cal-api-version: 2024-06-14` for event types
- `cal-api-version: 2024-06-11` for schedules

Common endpoints:

- `GET /v2/event-types`
- `GET /v2/event-types/{id}`
- `PATCH /v2/event-types/{id}`
- `GET /v2/schedules`
- `POST /v2/schedules`

Creating a non-default schedule and assigning its `id` to event types via `scheduleId` is a clean way to restrict public availability without changing the user's default working-hours schedule.

## Chrome Remote Debugging Prompt

Recent Chrome may show a native Russian prompt headed `Разрешить удаленную отладку?`. The `Разрешить` button must be clicked before CDP websocket connections work.
