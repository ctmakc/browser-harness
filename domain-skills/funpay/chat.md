# FunPay Chat

## URL Pattern

- Direct chat URL: `https://funpay.com/uk/chat/?node=<node_id>`.
- The active chat container is `.chat` and exposes:
  - `data-id`: numeric node id from the URL.
  - `data-name`: runner object name, for example `users-...`.
  - `data-user`: current FunPay user id.
  - `data-tag`: runner polling tag.
- The visible peer name is `.chat .media-user-name`.

## Stable Selectors

- Message textarea: `textarea[name="content"]`.
- Form: `textarea[name="content"]` closest `form`.
- Contact links: `a.contact-item[href*="/chat/?node="]`.

## Sending Messages

The form submit handler is attached by the app bundle and sends through `runner.sendRequest("chat_message", payload, ...)`.
Use the page handler instead of building the private request manually:

```python
msg = "..."
js("JSON.stringify((()=>{"
   "const ta=document.querySelector('textarea[name=\"content\"]');"
   "ta.focus();"
   "window.jQuery(ta).val(%s).trigger('input');"
   "window.jQuery(ta).closest('form').trigger('submit');"
   "return {ok:true};"
   "})())" % json.dumps(msg))
```

After sending, wait for a unique prefix of the message to appear in `document.body.innerText`.

## Verification

Before sending, verify both:

- `document.querySelector('.chat')?.dataset.id === "<node_id>"`
- `.chat .media-user-name` contains the expected seller name.

## Safety

Do not save cookies, CSRF tokens, passwords, or raw chat/order secrets in this domain skill. This file documents only durable page mechanics.
