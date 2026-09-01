<p align="center">
  <img src="branding/icloud-shared-album-sync-wordmark.png" alt="iCloud Shared Album Sync" width="780">
</p>

# iCloud Shared Album Sync for Home Assistant

Turn public iCloud Shared Albums into local, dashboard-friendly media libraries with a visual setup form—no YAML or folder-path configuration required.

This Home Assistant app downloads the best available photo or video for every item in one or more public shared albums. It creates a stable `index.json` for each album and an `albums.json` catalog that dashboards can use to discover new albums automatically.

## Highlights

- Multiple albums from one app
- Friendly add/remove album editor with sensible Home Assistant defaults
- Incremental downloads instead of downloading everything on every run
- Stable indexes with capture dates, media types, dimensions, and contributor names
- Safe mirror mode that never treats indexes or status files as photos
- `latest.jpg` generated from the newest available image
- Automatic root album catalog for guest-aware dashboards
- Per-album retention and mirror overrides
- Works with `/config/www`, `/media`, or `/share`

## Install

1. In Home Assistant, open **Settings → Apps → Install app**.
2. Open the three-dot menu and select **Repositories**.
3. Add `https://github.com/BZPJoe/icloud-shared-album-sync-repo`.
4. Find and install **iCloud Shared Album Sync**.
5. In its **Configuration** tab, add at least one public iCloud Shared Album URL.

See the [app documentation](icloud-shared-album-sync/DOCS.md) for configuration examples, guest album naming, output formats, migration notes, and troubleshooting.

## Privacy and scope

The app only works with albums that have an iCloud **Public Website** link. It does not request or store an Apple ID, password, or iCloud session cookie. Anyone with a public album URL can access that album, so treat the URL as sensitive.

## Development

Run the unit tests from the repository root:

```bash
python3 -m unittest discover -s icloud-shared-album-sync/tests -v
```

The project is licensed under the MIT License.
