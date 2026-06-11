# Dexcom Developer Portal

## URLs

- Developer home: `https://developer.dexcom.com/home`
- Login: `https://developer.dexcom.com/user/login`
- Register: `https://developer.dexcom.com/user/register`
- Forgot password: `https://developer.dexcom.com/user/forgot-password`
- Apps: `https://developer.dexcom.com/account/apps`
- Upgrade info: `https://developer.dexcom.com/support/upgrade-request`

## Account Notes

- `developer.dexcom.com` uses a separate account from the Dexcom store.
- Registration requires first name, last name, username, email, password, and the
  Registered Developer Agreement checkbox.
- The marketing updates checkbox is optional.
- Password reset emails come from `Dexcom Developers <noreply@mail.developer.dexcom.com>`.
- Gmail threads multiple reset emails together; the newest reset link appears last
  in `document.body.innerText` after opening the thread.
- Reset links expire quickly and become invalid after use; API failures surface as
  XHR `410` entries for `devportal/auth/reset-password`.

## App Setup

- Apps page has an `#add-app-button`.
- New apps first ask only for app name, then expand inline on the My Apps page.
- After expanding an app, useful selectors:
  - Description textarea: `#edit-attribute-appdescription0`
  - Add callback button: `#edit-submit-0`
  - Newly added callback input: `#new_callback_url-0-0`
  - Save button: `button[id^="edit-submit2"]`
  - Secret reveal link text: `Show`
- The app must have a saved Redirect URI before upgrade can be requested.
- Upgrade page currently routes developers to the Dexcom partnership page and says
  Dexcom expects apps to be created and tested against sandbox data before upgrade
  submission.

## Safety

- Do not write Client Secret, reset links, cookies, or session state into notes,
  screenshots, repo files, or logs.
