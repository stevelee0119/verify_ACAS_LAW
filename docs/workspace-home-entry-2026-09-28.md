# Initial Workspace Home

The earlier home-screen change was present only on
`codex/workspace-report-law-aliases`, not on deployed main `41e18b6`.
Main still restored `acas-project` from localStorage or opened the first
available project. This was a missing deployment, not a browser-cache issue.

On every fresh page load after authentication, list projects without opening
one. Keep the emblem and ACAS lettering visible until the user selects a
project in the sidebar. Existing projects, documents, runs and results remain
unchanged. Project creation and explicit navigation from background jobs keep
their existing behavior.

Replace the lettering with the user's supplied September 27 PNG, byte for byte.
SHA-256: `450ef32f5c07cf9f3f171ede4862d3e782a0018dd026c751220eda9db7f6c1fd`.
The versioned image URL also avoids retaining the prior cached lettering.

Tests cover existing, absent and stale remembered project IDs, desktop/mobile
entry, explicit project selection, reloading after selection, image dimensions
and rendered pixels. Existing project workflows now explicitly select their
project in tests, including the analysis retry regression.

This change does not incorporate the separate report-filename or law-alias
changes from the earlier branch. Release only after this commit passes CI;
verify fast-forward eligibility before publishing main, then verify Render's
commit, deployed assets, and the authenticated entry screen.
