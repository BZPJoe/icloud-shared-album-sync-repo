# iCloud Shared Album Sync

## What it creates

For an album configured with `media_subfolder: icloud-albums` and `album_subfolder: family`, the app creates:

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

## Recommended configuration

```yaml
interval_minutes: 180
timeout: 40
keep_days: 0
max_files: 500
mirror_missing: true
minimum_file_size_kb: 100
minimum_long_edge: 1280
catalog_filename: albums.json
debug: false
albums: |
  - name: Family Photos
    shared_url: "https://www.icloud.com/sharedalbum/#PUBLIC_ID_1"
    dest_mode: config_www
    media_subfolder: icloud-albums
    album_subfolder: family
    latest_filename: latest.jpg
    index_filename: index.json

  - name: Dee
    shared_url: "https://www.icloud.com/sharedalbum/#PUBLIC_ID_2"
    dest_mode: config_www
    media_subfolder: icloud-albums
    album_subfolder: dee

  - name: Dad and Janice
    shared_url: "https://www.icloud.com/sharedalbum/#PUBLIC_ID_3"
    dest_mode: config_www
    media_subfolder: icloud-albums
    album_subfolder: dad-and-janice

  - name: Robin
    shared_url: "https://www.icloud.com/sharedalbum/#PUBLIC_ID_4"
    dest_mode: config_www
    media_subfolder: icloud-albums
    album_subfolder: robin
```

The Office dashboard matches a visitor's calendar event to the album `name`. A calendar event called **Dee coming to stay** selects the album named **Dee** for each day covered by that event. When no visitor album matches, it falls back to the `family` folder.

## Album options

Every album supports these keys:

| Key | Required | Purpose |
| --- | --- | --- |
| `name` | Recommended | Friendly name exposed in `albums.json`. |
| `shared_url` | Yes | Public iCloud Shared Album link. |
| `dest_mode` | No | `config_www`, `media`, or `share`; default is `media`. |
| `media_subfolder` | No | Parent output folder. |
| `album_subfolder` | Yes | Stable folder slug for this album. |
| `index_filename` | No | Per-album index name; default `index.json`. |
| `latest_filename` | No | Copy of the newest image; default `latest.jpg`. Set to an empty string to disable. |
| `keep_days` | No | Overrides the global retention age. |
| `max_files` | No | Overrides the global file limit. |
| `mirror_missing` | No | Overrides global mirror behavior. |
| `minimum_file_size_kb` | No | Overrides the global derivative size floor. |
| `minimum_long_edge` | No | Overrides the global photo resolution floor. |

## Safe mirror behavior

Mirror mode only removes recognized photo and video files after Apple has returned a complete album listing. Indexes, status files, temporary files, and unrelated files are protected. If the album request fails, the existing library remains untouched.

## Retention

- `keep_days: 0` keeps files regardless of age.
- `max_files: 0` disables the count limit.
- Limits apply only to media files, never metadata.
- Retention is applied after a successful remote listing.

## Migrating from 0.4.3

Version 1.0 reads existing media filenames and reuses them when possible. Its first successful sync recreates the index and catalog. The old version could delete its own `index.json`; no manual repair is required.

The first run can take longer because it verifies the remote album. Later runs skip existing files and only download new items.

## Troubleshooting

### No media appears

- Confirm **Public Website** is enabled for the album.
- Confirm the full URL, including the text after `#`, is present in `shared_url`.
- Open the app log and look for an Apple request or validation error.

### Some images are skipped

The public album may only expose a small derivative for that item. Lower `minimum_long_edge` or `minimum_file_size_kb` for that album if you want to accept it.

### Dashboard does not discover a new guest album

- Keep guest albums under the same `dest_mode` and `media_subfolder` as the default album.
- Check that `/local/icloud-albums/albums.json` loads in Home Assistant.
- Make the calendar visitor name and album `name` match; phrases such as “coming to stay” and “visiting” are ignored by the Office dashboard.

### One album fails

Other albums continue syncing. The failed album keeps its last good media and index, and its `.icloud_album_sync.json` records the error.

## Index format

Each album index contains a version, album metadata, a generation timestamp, and an `items` array. Each item includes a stable iCloud GUID, local filename, public `/local` path when applicable, media type, capture date, dimensions, file size, caption, and contributor.

`albums.json` summarizes every configured album and points to its index. This lets a dashboard discover additional album folders without hardcoding them.
