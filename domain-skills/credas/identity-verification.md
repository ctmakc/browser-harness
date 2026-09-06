# Credas (myconnect.credas.com) — identity verification flow

Credas is a UK AML/KYC provider. Clients (law firms, company-formation agents,
virtual-office providers) send an invite email; the recipient completes ID checks.

## Invite link arrives HTML-escaped — rebuild it

The invite mail routes through SendGrid click tracking. After the redirect the
landing URL arrives with literal `&amp;` between query params:

```
https://myconnect.credas.com/landing?emailAddress=x@y.com&amp;registrationCode=ABCDEF&amp;method=3&amp;client=<uuid>&amp;process=<uuid>
```

Only `emailAddress` parses; `registrationCode` is swallowed, and the landing page
answers **"Sorry, we're unable to check your code. Please try again."** — which reads
like an expired invite and is not one.

Fix: rebuild the URL by hand with real `&` and a percent-encoded email:

```
https://myconnect.credas.com/landing?emailAddress=x%40y.com&registrationCode=ABCDEF&method=3&client=<uuid>&process=<uuid>
```

The registration code in the email body is hyphenated (`R2F-G3U`); the URL wants it
unhyphenated (`R2FG3U`).

## Terms page: Confirm silently no-ops until the terms are scrolled to the bottom

`/accept-terms` has a checkbox ("I have read and understand the terms") and a
`Confirm` button. Ticking the box is not enough. Until the inner `.terms-wrapper`
container is scrolled to its end, `Confirm` is **enabled, has a click listener,
fires no request, logs no error, and shows no validation message**. Easy to
misdiagnose as a dead button.

The container tracks a real scroll event, so setting `scrollTop` alone is unreliable —
send wheel events over it:

```python
r = json.loads(js("(()=>{const w=document.querySelector('.terms-wrapper');const b=w.getBoundingClientRect();return JSON.stringify({x:Math.round(b.x+b.width/2),y:Math.round(b.y+b.height/2)})})()"))
for _ in range(12):
    scroll(r["x"], r["y"], dy=400)
```

Then `Confirm` POSTs `api/entity-authentication/accept-terms` and routes on.
The same pattern applies to client-authored consent pages inside the task
(step 1 is often the client's own "Authority to Act" text with an
"I agree to the above" checkbox).

## Flow shape

1. `/landing` → `Let's get started` → POST `api/entity-authentication/register`
2. `/accept-terms` → Credas platform T&Cs (see scroll trap above)
3. `/device` → "Download the mobile app" / "Switch to mobile" / **Continue on desktop**
4. `/portal/<clientId>/task/<processId>` → numbered steps, saved server-side via
   `PUT api/tasks/<taskId>/...` so navigating back and forth loses nothing.

Typical task steps: client consent page → forename/surname/DOB → document briefing →
proof of ID (radio: Passport / Driving Licence / Travel Permit / Visa / Proof of Age /
National ID) → capture.

## Document capture is camera-only — there is no file upload

At the capture step the desktop path renders a `<video>` element and a "Take photo"
button. There is **no `input[type=file]`** anywhere in the DOM, so a stored scan of the
passport cannot be submitted. Both the document photo and the selfie need the real
person and the real document in front of a camera.

Plan for this: drive the flow up to the capture step, then hand off. "Switch to mobile"
renders a 256×256 `<canvas>` QR — screenshot it and send it to the person; they finish
document + selfie on the phone, and Credas itself reports the highest pass rates for
the mobile path.

## Angular, not React

The app is Angular Material (`mat-mdc-checkbox`, `mat-input-*`). Checkbox state is
readable from the wrapper class (`mat-mdc-checkbox-checked ng-dirty ng-valid ng-touched`).
Buttons carry no id/href — locate by `innerText`, then click by bounding box.
Text inputs use `formcontrolname="answer"` and need the native value setter plus
`input`/`change`/`blur` events.
