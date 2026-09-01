# Changelog

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
