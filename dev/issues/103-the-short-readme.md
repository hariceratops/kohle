# [feat] The short README

Cut the README to what sells the app and point to the guide, once every moved section has a page.

Depends on: 093-102

## Acceptance Criteria

- `README.md` holds the pitch, succinct key features, the "still a bit personalized" warning, a taste, a link to the guide with how to read it locally, and a roadmap.
- The taste is one end-to-end session (create accounts, import a statement, classify, run a report) showing each command and its output, and its commands are checked examples.
- The roadmap is built from the `dev/inbox` briefs, leaves out delivered or already documented work, and contains no personal data or preferences.
- No command options or report columns remain in the README.
- Every statement removed from the README exists on a guide page, was cut as stale or duplicated, or went to the developer site.
- The key features are marked in the PR description as drafted for the author to edit.
