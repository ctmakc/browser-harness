# Pinterest — settings, website claiming, developer apps

Measured live on a logged-in ru-locale business account, 2026-08-14. Covers three
surfaces that look separate but share one identity: `/settings/`, `/settings/claim/`,
and `developers.pinterest.com`.

## URL map

| Surface | Path |
|---|---|
| Profile fields (name, bio, site, username, contact, address) | `/settings/edit-profile` |
| Email, password, account type, deactivate | `/settings/account-settings/` |
| Claim websites / other platforms | `/settings/claim/` |
| Developer apps list | `https://developers.pinterest.com/apps/` |
| New app request form | `https://developers.pinterest.com/apps/connect/` |

**The host is not stable.** `www.pinterest.com/settings/...` 302s to the account's
regional host — e.g. `ca.pinterest.com/settings/edit-profile`. Never assert on
`location.host === 'www.pinterest.com'`, and never build follow-up URLs by string
concatenation onto `www.`; read `location.origin` after `wait_for_load()` instead.
Note that the *developer* portal does not do this — it stays on
`developers.pinterest.com`.

## Edit profile — stable IDs, React-controlled inputs

The form uses real element **ids**, not CSS-module classes. These are the durable
selectors:

```
#business_name          #about (textarea)      #website_url
#username               #partner_contact_email #phoneNumber
#enable_profile_address (toggle)
#partner_address_line_1 #partner_address_line_2
#partner_city           #partner_region        #partner_postal_code
```

**Account-type detection:** presence of `#business_name` plus the `#partner_*` block
means a **business** account. A personal account renders neither. This is a cheaper
and more reliable check than reading any badge or menu label.

### The trap: setting `.value` does nothing

Every input is a controlled React component. Assigning `el.value = x` updates the DOM
node but not React's internal state, so the next render wipes it and Save posts the
old value — with no error anywhere. You must go through the **native value setter**
and then fire bubbling events React actually listens to:

```python
js("""
(() => {
  const setNative = (el, val) => {
    const proto = el.tagName === 'TEXTAREA'
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, val);
    el.dispatchEvent(new Event('input',  {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  };
  const fields = {business_name: 'Acme', about: 'Bio text', website_url: 'https://example.com'};
  const missing = [];
  for (const [id, val] of Object.entries(fields)) {
    const el = document.getElementById(id);
    if (!el) { missing.push(id); continue; }
    setNative(el, val);
  }
  return JSON.stringify({missing});
})()
""")
```

`#about` is a `<textarea>` — use `HTMLTextAreaElement.prototype`, otherwise the
descriptor lookup returns the wrong setter and the write silently no-ops.

Read back with `document.getElementById(id).value` after a short wait; if a field
reverted, the event dispatch was the thing that failed, not the typing.

### Save button

The save control is a plain `<button>` whose **exact `innerText` is locale-dependent**
(`Сохранить` on ru). Do not hardcode the string as your only strategy. Locate it by
position — the last enabled submit-ish `<button>` inside the settings form — and use
the label only as a confirmation:

```python
js("""
(() => {
  const btns = [...document.querySelectorAll('button')]
    .filter(b => !b.disabled && b.getBoundingClientRect().width > 0);
  const b = btns[btns.length - 1];
  return b ? b.innerText.trim() : 'none';
})()
""")
```

Screenshot after saving — the success toast is the only visible confirmation.

### Trap: the saved URL comes back as `http://`

Pinterest **normalizes `https://example.com` to `http://example.com`** in
`#website_url` after save. The scheme change is Pinterest's, not a failed write. Assert
on the host, not the full string, or you will loop retrying a save that already worked.

## Account settings — email is on screen but not in the DOM text

`/settings/account-settings/` renders the email address visibly, but `innerText`
scraping returns a masked placeholder (`Скрытая информация` on ru). The real value is
painted, not in the text nodes you can reach.

**So: read it from a `screenshot()`, not from the DOM.** Any innerText-based extractor
will confidently return the mask string and you will report the wrong address.

## Claiming a website

`/settings/claim/` lists claimable destinations as rows. The **Веб-сайты** row's verify
button opens a modal. Modal contents:

- `#domain-verification-input` — the URL, **prefilled from the profile's
  `#website_url`**. If you just changed the website in edit-profile, this is where that
  change shows up. It is a controlled input too — same native-setter dance as above.
- Three radios sharing `name="websiteVerification"`, with ids
  `#metatag`, `#filename`, `#dnstxt`.

Selecting `#dnstxt` reveals a TXT record value of the shape:

```
pinterest-site-verification=<32 hex chars>
```

The **same 32-hex token** is reused in the metatag variant
(`<meta name="p:domain_verify" content="…">`), so you only need to extract it once —
pick whichever method the site's infrastructure supports and reuse the value. (Never
commit a real token to this repo; the shape above is the contract, nothing more.)

### The two-button trap

After the DNS TXT propagates, the modal's submit control reads `Подтверждение
веб-сайта`, while the underlying row still carries its own `Подтвердить` button.
**Both are in the DOM at the same time**, and the row's one is often hidden behind the
modal with a zero-size bounding rect. Filter for visibility and prefer the *last*
match:

```python
js("""
(() => {
  const hits = [...document.querySelectorAll('button')]
    .filter(b => /подтвержд/i.test(b.innerText || ''))
    .filter(b => { const r = b.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
  const b = hits[hits.length - 1];
  if (!b) return 'no_visible_button';
  b.click();
  return 'clicked:' + b.innerText.trim();
})()
""")
```

**Success assertion:** a claimed domain renders an **`Отменить подтверждение`** control
in its row. Presence of that (not a toast, not the absence of an error) is the durable
proof the claim landed. Re-navigate to `/settings/claim/` and check for it.

DNS propagation is the slow part and `wait_for_load()` says nothing about it. Expect to
close the modal, wait out the TTL, and reopen `/settings/claim/` later rather than
holding the modal open.

## Invisible reCAPTCHA

Settings and claim pages carry an invisible reCAPTCHA: a `textarea` named
`g-recaptcha-response` is present in the DOM and **auto-populates on its own** during
normal interaction. Do not try to read, solve, forge, or clear it — and do not treat
its empty state as a blocker. If a save fails, the cause is almost always the
controlled-input problem above, not the captcha.

## Developer portal — `developers.pinterest.com`

### Getting to the form

The "Подключить приложение" control is an `<a href="/apps/connect/">`, and there are
**three matches in the DOM, two of which have a zero-size bounding rect** (nav/mobile
duplicates). Clicking the first match does nothing.

**Just navigate to `https://developers.pinterest.com/apps/connect/` directly** — it is
more reliable than any click. If you must click, filter by `getBoundingClientRect().width > 0`.

### `/apps/connect/` field ids

```
#upload-icon        (file input)
#name               #companyName
#mainUrl            #privacyPolicyUrl
#description        #developerPurpose
```

Radios — developer purpose:
`#mcp_ai`, `#personal_api_access`, `#consumer_experience`, `#other`

Checkboxes — use cases (`#use_case_categories_*`):
`creation`, `reporting`, `ads_management`, `pinner_app`, `ecommerce`,
`recommendation_exp`, `other`

Checkboxes — audience (`#audience_categories_*`):
`pinner`, `creator`, `advertiser`, `merchant`, `business`, `other`

Radios `name="pinner_data_access"`:
`#pinner_data_access_none`, `#pinner_data_access_personal`, `#pinner_data_access_general`

Same React-controlled-input rules apply to the text fields. For radios and checkboxes,
a plain `.click()` on the element works (the change goes through the label's handler);
verify with `.checked` afterwards.

### Hard prerequisite

**`#privacyPolicyUrl` is required.** A project with no public privacy-policy page
cannot complete this form — there is no skip. Check this *before* starting the flow;
otherwise you fill eight fields and stall at submit.

### Access tiers and quotas

| | Trial | Standard |
|---|---|---|
| Rate limit | 1000 requests/day | variable |
| Pin visibility | Pins created via the API are visible **only to their creator** | public |
| Approval | immediate | requires review |

The Trial visibility rule is the one that bites: a script can report "pin created"
and be correct, while the pin is invisible to everyone else. Do not diagnose that as a
bug.

Other ceilings: **one app request pending at a time**, **5 apps maximum** per account.
