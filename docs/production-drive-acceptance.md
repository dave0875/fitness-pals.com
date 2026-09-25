# Production Google Drive acceptance

The CI/CD workflow contains an opt-in production acceptance test for the authenticated Google Drive Garmin archive-import path.

## Trigger

The merge commit message must contain the exact marker:

`[prod-drive-acceptance]`

When present on a push to `main`, the production deployment runs `app.ops.prod_drive_acceptance` after the normal public production journey smoke check. This is intentionally opt-in because it exercises the real production OAuth-backed Drive import path rather than only static or mocked contracts.

## Release rule

For changes to the production Google Drive archive-import path, do not treat deployment success alone as acceptance. Require the `Accept production Google Drive OAuth import` workflow step to reach terminal `success` on the deployed SHA.

This document was added while closing the end-to-end acceptance gap discovered after PR #270.
