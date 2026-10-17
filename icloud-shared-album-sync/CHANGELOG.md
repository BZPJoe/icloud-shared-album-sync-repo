# Changelog

## 1.2.2

- Normalize new custom folder names to lowercase dashboard-safe slugs; reuse existing configured folders without renaming their media or dashboard paths.
- Reject destination collisions before synchronization.
- Preserve existing indexes and skip cleanup after failed or truncated downloads; reject malformed listings and repeated pagination markers.
- Avoid exposing signed request URLs in request/download errors or HTTP debug logs.
- Retain optional legacy album fields in the visual editor schema and document manual saved-options conversion, advanced settings, backup/rollback, and removal of armv7 support.
- Mark 1.2.2 as requiring upgrade attention in Home Assistant.
- Explain the automatic folder-name conversion in the visual settings form and documentation.

## 1.2.1

- Prefer Apple's dashboard-friendly JPEG derivative for current-format photo albums, including albums whose original uploads are HEIC or RAW.

## 1.2.0

- Added support for Apple's current `photos.icloud.com/shared/album/…` public-link format.
- Kept compatibility with legacy `www.icloud.com/sharedalbum/#…` links.
- Added pagination, quality filtering, and dashboard indexes for current-format albums.
- Documented the two supported public-link formats and the app's short-lived anonymous access flow.

## 1.1.3

- Use the colorful icon by itself in Home Assistant's compact app header.
- Show the full iCloud Shared Album Sync wordmark prominently above the app description.

## 1.1.2

- Fixed repeatable album-editor entries being misread when Home Assistant passes them to the sync engine as JSON text.
- Added regression coverage for the exact saved-options format used by the running app.

## 1.1.1

- Installed the new iCloud Shared Album Sync artwork in Home Assistant's required app icon and logo locations.
- Bumped the app version so repository and browser caches refresh the new branding.

## 1.1.0

- Replaced the raw albums YAML textbox with a repeatable album editor.
- Reduced each album to a friendly name, public link, optional folder name, and enable switch.
- Added safe Home Assistant dashboard defaults for output paths and index filenames.
- Grouped network, retention, quality, catalog, and debug controls under Advanced settings.
- Kept compatibility with albums saved by earlier versions.
- Updated the Home Assistant configuration mount and supported architectures for current app-platform requirements.

## 1.0.2

- Read the app's own options directly from its private data mount, avoiding an unnecessary Supervisor API permission.

## 1.0.1

- Grant the app access to its saved Supervisor configuration so runtime options load correctly.

## 1.0.0

- Rebuilt sync engine around stable iCloud photo GUIDs and derivative checksums.
- Added incremental downloads and atomic file/index writes.
- Added a versioned per-album `index.json` with capture metadata.
- Added an automatic root `albums.json` discovery catalog.
- Added reliable `latest.jpg` generation from the newest image.
- Fixed mirror mode deleting `index.json`, `latest.jpg`, and other metadata.
- Fixed duplicate index entries and filename mismatches caused by `Content-Disposition`.
- Added per-album retention, mirror, size, and resolution overrides.
- Added safe partial-failure behavior that preserves the last good library.
- Removed unused Selenium, Chromium, ChromeDriver, and Beautiful Soup packages.
- Added unit tests, automated validation, migration notes, and full documentation.
