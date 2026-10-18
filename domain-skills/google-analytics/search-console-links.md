# Google Analytics: Search Console links

## Route and background rendering

GA4 admin routes include both account and property IDs:
`https://analytics.google.com/analytics/web/#/a<accountId>p<propertyId>/admin/integrations/search-console`.

`open_url()` ignores URL fragments in its default reuse check. Pass a `match` containing the account/property/route fragment when navigating between GA4 properties; otherwise the helper silently remains on the previous property. Verify the visible property name and table, not only `location.href`.

The Angular interface can leave panels outside the viewport and defer transitions in a background tab. On the agent's own tab, `cdp('Emulation.setFocusEmulationEnabled', enabled=True)` makes the page report visible without activating the owner's foreground tab. Restore it to false before ending the task. Wait for the actual next control/state, not only `document.readyState`.

Background screenshots can still time out. Avoid repeating a timed-out screenshot: the harness may recover to a blank tab, losing an unsaved wizard. In that case inspect the DOM and use observed semantic controls. Recheck the saved link before retrying any mutation.

## Migration shape

A link cannot be edited: delete the old link, then create its replacement. Before deletion record the exact Search Console resource, GA4 property, stream name and stream ID. Confirm the replacement GSC resource is verified and accessible. Preserve the same data stream.

- Links table uses `mat-row[role=row]`.
- The row's details button has a localized aria label (Russian: `Показать сведения о ссылке`).
- The details panel overflow menu leads to Delete and a confirmation dialog.
- The creation wizard selects GSC property, data stream, then displays a review before submission.
- In the property chooser, search is `input[aria-label="Поиск"]` in Russian. The global search has the same label: scope to the current chooser, or inspect all matches before selecting one.
- A GSC property row includes its name plus type (`Домен` or `Ресурс с префиксом в URL`); match both exactly. Linked resources may have a link icon instead of a selectable checkbox.
- **Data-stream rows have `[data-guidedhelpid="choose-stream"]`, with `.name` and `.stream-id` children.** Match the `.name` inside this row. A generic text match may click the global property picker or a hidden tooltip instead.
- Verify the success result (`СВЯЗЬ СОЗДАНА` in Russian) and the resulting table's resource/type and unchanged stream ID.

UI actions and property changes require authorization from the current owner task. Do not interpret this guide as authorization to unlink accounts.
