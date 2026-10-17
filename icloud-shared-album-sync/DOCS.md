# iCloud Shared Album Sync

## What it creates

For an album whose folder name is `family`, the app creates:

```text
/config/www/icloud-albums/
├── albums.json
└── family/
    ├── index.json
    ├── latest.jpg
    ├── .icloud_album_sync.json
    └── photos and videos…
```

Home Assistant serves `/config/www` at `/local`, so the catalog is available to a dashboard as `/local/icloud-albums/albums.json`.

## Get a public album URL

1. Open Photos on an Apple device.
2. Open or create a Shared Album.
3. Enable **Public Website** for that album.
4. Copy its iCloud link.

The app supports both iCloud public-link styles: newer links beginning with `https://photos.icloud.com/shared/album/…` and the older `https://www.icloud.com/sharedalbum/#…` links. Paste the whole link exactly as Photos gives it to you—there is no need to convert it.

Public links do not require an Apple login. The app uses Apple's short-lived anonymous access token only while syncing; it never stores an Apple ID, password, browser cookie, or that token. Anyone with the link can view the shared album, so do not post it in issues or logs.

## Add an album

1. Open the app's **Configuration** tab.
2. Under **Photo albums**, choose **Add**.
3. Enter a display name, such as `Family Photos`, `Dee`, or `Dad and Janice`.
4. Paste the public iCloud Shared Album link.
5. Leave **Folder name** blank unless a dashboard already uses a specific folder. New folder names are converted to lowercase words joined with hyphens—`Family Visits` becomes `family-visits`. An explicitly configured folder that already exists is kept in place, preserving its media, indexes, and dashboard URLs.
6. Save and restart the app.

The app automatically stores dashboard media under `/config/www/icloud-albums`, creates `index.json` and `latest.jpg`, and adds the album to `albums.json`. You do not need to write YAML or choose output paths.

Use the **Sync this album** switch to pause an album without losing its setup. The recommended sync and cleanup settings are already filled in. Network, retention, image-quality, catalog, and debug controls are grouped under **Advanced settings**.

Dashboard integrations are configured separately. This app supplies media and JSON catalogs; it does not install a dashboard or calendar integration.

## Album fields

Every album has these friendly fields:

| Key | Required | Purpose |
| --- | --- | --- |
| `Display name` | Yes | Friendly name exposed to dashboards and used to generate a folder name. |
| `Public iCloud link` | Yes | Full link copied after enabling **Public Website** in Apple Photos. |
| `Folder name` | No | Stable dashboard folder. Leave blank to generate it from the display name. New folders are normalized; existing explicitly configured folders retain their names. |
| `Sync this album` | No | Pause or resume an album without deleting it. |

## Safe mirror behavior

Mirror mode only removes recognized photo and video files after Apple has returned a complete album listing. Indexes, status files, temporary files, and unrelated files are protected. If the album request fails, the existing library remains untouched.

## Retention

- **Delete photos older than: 0** keeps files regardless of age.
- **Maximum items per album: 0** disables the count limit.
- Limits apply only to media files, never metadata.
- Retention is applied after a successful remote listing.

## Updating from an earlier version

### Updating from 1.0.2 to 1.2.2

This release changes the Home Assistant options schema. It is marked as a breaking version so automatic updates require attention. The sync engine can still read legacy YAML and top-level advanced options, but the Supervisor visual editor does not automatically convert a YAML string into album rows. Do not assume saving the new form preserves old fields.

1. Stop the app. Back up its complete saved configuration privately, plus every destination media folder, including indexes, catalog, `latest.jpg`, and `.icloud_album_sync.json`. Home Assistant app backups may not include separately mounted `/config/www`, `/media`, or `/share` files; back those up explicitly.
2. Confirm the host uses **amd64 or aarch64**. The former armv7 target is no longer offered; 32-bit installations must remain on the older release or migrate to a supported host.
3. Update, then open Configuration. If `albums` remains a YAML text block, use **Edit in YAML** to replace that scalar with a list of mappings (remove the `|` and unindent its entries). Keep each original URL and every custom field. Do not replace your private links with the examples.
4. Move top-level `timeout`, `keep_days`, `max_files`, `minimum_file_size_kb`, `minimum_long_edge`, `catalog_filename`, and `debug` into `advanced`. Keep `interval_minutes` and `mirror_missing` at the top level. Preserve the old values; new defaults must not silently replace retention choices.
5. Preserve each album's `dest_mode`, `media_subfolder`, `album_subfolder`, `latest_filename`, `index_filename`, and per-album overrides. These optional legacy fields remain accepted by the schema. Existing explicitly configured folders are reused without renaming. New normalized names must be unique within the same destination root.
6. Save, review the resulting rows and YAML, and restart. Verify media counts, catalog/index URLs and the next incremental sync. For the first verification run, consider `mirror_missing: false`, `keep_days: 0`, and `max_files: 0`; restore your chosen cleanup settings after checking the result.

Example structure (synthetic link only):

```yaml
albums:
  - name: Family Photos
    shared_url: https://www.icloud.com/sharedalbum/#YOUR_PUBLIC_ALBUM_ID
    dest_mode: config_www
    media_subfolder: icloud-albums
    album_subfolder: family
    enabled: true
interval_minutes: 180
mirror_missing: false
advanced:
  timeout: 40
  keep_days: 0
  max_files: 0
  minimum_file_size_kb: 100
  minimum_long_edge: 1280
  catalog_filename: albums.json
  debug: false
```

The mount now explicitly maps `homeassistant_config` to `/config`; `/media` and `/share` remain writable. No media directory or index format migration is required. Current-format albums prefer an available JPEG meeting the quality floor, including for HEIC/RAW uploads. If Apple does not supply a qualifying JPEG, the original may still be selected; this app does not transcode it.

For rollback, stop the app and restore the previous app version and its saved options together. Restore backed-up media/indexes if needed. Do not uninstall or delete destination folders as an upgrade step.

### Validation still needed on a running Home Assistant host

Verify a real 1.0.2 saved-options upgrade through Supervisor, editor save/restart, mount permissions, amd64/aarch64 container builds, incremental synchronization with both public-link styles, HEIC/RAW JPEG display, and dashboard URLs after folder preservation. Automated tests use synthetic responses and temporary files; they do not establish live Apple API or Supervisor behavior.

### Migrating from 0.4.3

Version 1.0 reads existing media filenames and reuses them when possible. Its first successful sync recreates the index and catalog. The old version could delete its own `index.json`; no manual repair is required.

The first run can take longer because it verifies the remote album. Later runs skip existing files and only download new items.

## Troubleshooting

### No media appears

- Confirm **Public Website** is enabled for the album.
- Paste the full link copied from Photos. Older links require the text after `#`; newer `photos.icloud.com/shared/album/…` links do not use `#`.
- Open the app log and look for an Apple request or validation error.

### Some images are skipped

The public album may only expose a small derivative for that item. Open **Advanced settings** and lower **Minimum photo resolution** or **Minimum file size** if you want to accept it.

### Dashboard does not discover a new guest album

- Check that `/local/icloud-albums/albums.json` loads in Home Assistant.
- Check your dashboard integration separately; visitor/calendar matching is not part of this app.

### One album fails

Other albums continue syncing. The failed album keeps its last good media and index, and its `.icloud_album_sync.json` records the error.

## Index format

Each album index contains a version, album metadata, a generation timestamp, and an `items` array. Each item includes a stable iCloud GUID, local filename, public `/local` path when applicable, media type, capture date, dimensions, file size, caption, and contributor.

`albums.json` summarizes every configured album and points to its index. This lets a dashboard discover additional album folders without hardcoding them.
