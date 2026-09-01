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

Public links do not require an Apple login. Anyone with the link can view the shared album, so do not post it in issues or logs.

## Add an album

1. Open the app's **Configuration** tab.
2. Under **Photo albums**, choose **Add**.
3. Enter a display name, such as `Family Photos`, `Dee`, or `Dad and Janice`.
4. Paste the public iCloud Shared Album link.
5. Leave **Folder name** blank unless a dashboard already uses a specific folder.
6. Save and restart the app.

The app automatically stores dashboard media under `/config/www/icloud-albums`, creates `index.json` and `latest.jpg`, and adds the album to `albums.json`. You do not need to write YAML or choose output paths.

Use the **Sync this album** switch to pause an album without losing its setup. The recommended sync and cleanup settings are already filled in. Network, retention, image-quality, catalog, and debug controls are grouped under **Advanced settings**.

The Office dashboard matches a visitor's calendar event to the album `name`. A calendar event called **Dee coming to stay** selects the album named **Dee** for each day covered by that event. When no visitor album matches, it falls back to the `family` folder.

## Album fields

Every album has these friendly fields:

| Key | Required | Purpose |
| --- | --- | --- |
| `Display name` | Yes | Friendly name exposed to dashboards and used to generate a folder name. |
| `Public iCloud link` | Yes | Full link copied after enabling **Public Website** in Apple Photos. |
| `Folder name` | No | Stable dashboard folder. Leave blank to generate it from the display name. |
| `Sync this album` | No | Pause or resume an album without deleting it. |

## Safe mirror behavior

Mirror mode only removes recognized photo and video files after Apple has returned a complete album listing. Indexes, status files, temporary files, and unrelated files are protected. If the album request fails, the existing library remains untouched.

## Retention

- **Delete photos older than: 0** keeps files regardless of age.
- **Maximum items per album: 0** disables the count limit.
- Limits apply only to media files, never metadata.
- Retention is applied after a successful remote listing.

## Updating from an earlier version

Version 1.1 replaces the raw YAML album box with a visual add/remove editor. Existing album entries continue to work. After updating, open **Configuration**, confirm each album appears as a row, and save once to store it in the new format.

### Migrating from 0.4.3

Version 1.0 reads existing media filenames and reuses them when possible. Its first successful sync recreates the index and catalog. The old version could delete its own `index.json`; no manual repair is required.

The first run can take longer because it verifies the remote album. Later runs skip existing files and only download new items.

## Troubleshooting

### No media appears

- Confirm **Public Website** is enabled for the album.
- Confirm the full URL, including the text after `#`, is present in `shared_url`.
- Open the app log and look for an Apple request or validation error.

### Some images are skipped

The public album may only expose a small derivative for that item. Open **Advanced settings** and lower **Minimum photo resolution** or **Minimum file size** if you want to accept it.

### Dashboard does not discover a new guest album

- Check that `/local/icloud-albums/albums.json` loads in Home Assistant.
- Make the calendar visitor name and album `name` match; phrases such as “coming to stay” and “visiting” are ignored by the Office dashboard.

### One album fails

Other albums continue syncing. The failed album keeps its last good media and index, and its `.icloud_album_sync.json` records the error.

## Index format

Each album index contains a version, album metadata, a generation timestamp, and an `items` array. Each item includes a stable iCloud GUID, local filename, public `/local` path when applicable, media type, capture date, dimensions, file size, caption, and contributor.

`albums.json` summarizes every configured album and points to its index. This lets a dashboard discover additional album folders without hardcoding them.
