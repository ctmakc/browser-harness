# Search Console resources and dependencies

Useful settings routes:

- `/search-console/settings?resource_id=<encoded property>`
- `/search-console/settings/associations?resource_id=<encoded property>`

A property identifier is an exact URL prefix, including its trailing slash, or `sc-domain:<domain>`.

A domain property can display associations belonging to URL-prefix children. The URL column identifies the actual associated resource. Seeing a GA4 association in the domain property's table does **not** prove GA4 is linked directly to the domain: check GA4's Search Console Links table for the exact resource and resource type.

To consolidate authorized overlapping resources, inventory consumers first: API applications, analytics source records, onboarding/configuration registries, GA4 associations and sitemap registrations. A database often has both a site-level property binding and a separate synchronization source; update both while preserving historical records. Keep DNS and HTML verification tokens intact: deleting a user's redundant listing is distinct from revoking ownership or removing a site from search.

The official Search Console API `sites.delete` removes a property from the calling user's list. Re-read `sites.list` after a change and verify that the intended replacement remains accessible. Save the exact old identifiers for reversible re-addition using `sites.add`.
