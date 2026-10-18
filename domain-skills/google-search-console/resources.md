# Search Console resources and dependencies

Useful settings routes:

- `/search-console/settings?resource_id=<encoded property>`
- `/search-console/settings/associations?resource_id=<encoded property>`

A property identifier is an exact URL prefix, including its trailing slash, or `sc-domain:<domain>`.

A domain property can display associations belonging to URL-prefix children. The URL column identifies the actual associated resource. Seeing a GA4 association in the domain property's table does **not** prove GA4 is linked directly to the domain: check GA4's Search Console Links table for the exact resource and resource type.

To consolidate authorized overlapping resources, inventory consumers first: API applications, analytics source records, onboarding/configuration registries, GA4 associations and sitemap registrations. A database often has both a site-level property binding and a separate synchronization source; update both while preserving historical records. Keep DNS and HTML verification tokens intact: deleting a user's redundant listing is distinct from revoking ownership or removing a site from search.

The official Search Console API `sites.delete` removes a property from the calling user's list. Re-read `sites.list` after a change and verify that the intended replacement remains accessible. Save the exact old identifiers for reversible re-addition using `sites.add`.

## Sitemap and indexing diagnostics

- Sitemap overview: `/search-console/sitemaps?resource_id=<encoded property>`. Each entry is a `tr[data-full-feedpath="<sitemap URL>"]`; clicking it opens `/search-console/sitemaps/info-drilldown?resource_id=…&sitemap=…`.
- The API can expose a nonzero `warnings` count while both the overview and detail UI report successful processing with no expandable warning list. Record this discrepancy; do not invent a cause from the count or claim warnings have been fixed.
- Page indexing: `/search-console/index?resource_id=…`. Click the reason's table row to open its examples. The resulting `/index/drilldown` URL includes an opaque `item_key`; obtain it from the page instead of assuming it applies to other filters.
- The SPA retains hidden tables from previous reports. `querySelectorAll('tr')` alone includes stale rows. Restrict extraction to rendered rows or parse the visible `document.body.innerText` after the report changes.
- The examples page size is `[role=listbox][aria-label="Количество строк на страницу"]` in Russian. Open its `[jsname=LgbsSe]`, then select the rendered `[role=option][data-value="250"]`. Confirm the resulting range/count.
- URL examples may contain spaces and non-ASCII characters. Extract whole URL lines, not whitespace-delimited tokens, and URL-encode before HTTP checks; otherwise malformed URLs can be silently truncated into healthy ones.
- Validation can be verified by the displayed started status and start date. An indexing request first performs a live check; wait for the final confirmation that the URL entered the priority crawl queue, rather than treating the button click as success.
