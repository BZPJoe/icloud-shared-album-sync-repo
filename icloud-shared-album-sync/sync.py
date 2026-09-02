#!/usr/bin/env python3
"""Synchronize public iCloud Shared Albums into Home Assistant folders."""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import shutil
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, unquote, urlparse

import requests
import yaml


APPLE_BOOTSTRAP_HOST = "p23-sharedstreams.icloud.com"
APPLE_CLOUDKIT_CONTAINER = "com.apple.photos.cloud"
MODERN_SHARED_ALBUM_HOSTS = {"photos.icloud.com", "photos.icloud.com.cn"}
MEDIA_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".heic",
    ".heif",
    ".mp4",
    ".mov",
    ".m4v",
}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}
SINGLE_LINE_KEY = re.compile(
    r"(?<!\S)(name|shared_url|dest_mode|media_subfolder|album_subfolder|"
    r"latest_filename|index_filename|keep_days|max_files|mirror_missing|"
    r"minimum_file_size_kb|minimum_long_edge)\s*:"
)
SAFE_SLUG = re.compile(r"[^a-z0-9]+")


class SyncError(RuntimeError):
    """An album could not be listed or synchronized safely."""


@dataclass(frozen=True)
class RemoteItem:
    guid: str
    filename: str
    source_url: str
    media_type: str
    captured_at: str | None
    width: int
    height: int
    expected_size: int
    caption: str
    contributor: str


@dataclass
class AlbumResult:
    name: str
    slug: str
    destination: Path
    public_base: str | None
    index_filename: str
    latest_filename: str | None
    item_count: int
    status: str
    synced_at: str
    error: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def setup_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", "", "none", "null"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected a boolean, received {value!r}")


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = SAFE_SLUG.sub("-", ascii_value.lower()).strip("-")
    return slug or "album"


def safe_filename(value: str, guid: str, media_type: str) -> str:
    value = unquote(value or "").replace("\\", "/").rsplit("/", 1)[-1]
    value = unicodedata.normalize("NFKC", value)
    value = "".join(ch for ch in value if ch >= " " and ch not in '<>:"/\\|?*')
    value = value.strip(" .")
    if not value:
        value = f"icloud-{guid[:12]}.{'mp4' if media_type == 'video' else 'jpg'}"
    stem, suffix = os.path.splitext(value)
    if not suffix:
        suffix = ".mp4" if media_type == "video" else ".jpg"
    return f"{stem[:180]}{suffix}"


def normalize_single_line_yaml(value: str) -> str:
    stripped = value.strip()
    if "\n" in stripped and re.search(r"^\s*-\s+", stripped, re.MULTILINE):
        return stripped
    if not stripped.startswith("- "):
        stripped = "- " + stripped
    body = stripped[2:]
    matches = list(SINGLE_LINE_KEY.finditer(body))
    if not matches:
        return stripped
    lines: list[str] = []
    for index, match in enumerate(matches):
        next_start = matches[index + 1].start(1) if index + 1 < len(matches) else len(body)
        key = match.group(1)
        raw_value = body[match.end() : next_start].strip()
        prefix = "- " if index == 0 else "  "
        lines.append(f"{prefix}{key}: {raw_value}".rstrip())
    return "\n".join(lines)


def parse_albums(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        stripped = value.strip()
        try:
            if stripped.startswith("[") or stripped.startswith("{"):
                parsed = json.loads(stripped)
            else:
                parsed = yaml.safe_load(normalize_single_line_yaml(stripped))
        except (json.JSONDecodeError, yaml.YAMLError) as error:
            raise SyncError(f"Invalid albums configuration: {error}") from error
    else:
        parsed = value
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list) or not parsed:
        raise SyncError("The albums option must contain at least one album.")
    albums: list[dict[str, Any]] = []
    for position, album in enumerate(parsed, start=1):
        if not isinstance(album, dict):
            raise SyncError(f"Album {position} is not a valid album entry.")
        if not parse_bool(album.get("enabled", True)):
            continue
        normalized_album = dict(album)
        name = str(normalized_album.get("name") or "").strip()
        if not normalized_album.get("shared_url"):
            raise SyncError(f"Album {position} requires a public iCloud link.")
        if not name:
            name = "Shared Album"
        normalized_album["name"] = name
        normalized_album["album_subfolder"] = str(
            normalized_album.get("album_subfolder") or slugify(name)
        ).strip()
        normalized_album.setdefault("dest_mode", "config_www")
        normalized_album.setdefault("media_subfolder", "icloud-albums")
        normalized_album.setdefault("index_filename", "index.json")
        normalized_album.setdefault("latest_filename", "latest.jpg")
        albums.append(normalized_album)
    if not albums:
        raise SyncError("At least one album must be enabled.")
    return albums


def album_id_from_url(shared_url: str) -> str:
    parsed = urlparse(shared_url.strip())
    album_id = parsed.fragment.strip()
    if not album_id:
        raise SyncError("The public album URL must include its #album-id fragment.")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", album_id):
        raise SyncError("The public album ID contains unexpected characters.")
    return album_id


def modern_album_id_from_url(shared_url: str) -> str | None:
    """Return the opaque ID used by Apple's newer photos.icloud.com links."""
    parsed = urlparse(shared_url.strip())
    if parsed.hostname not in MODERN_SHARED_ALBUM_HOSTS:
        return None
    match = re.fullmatch(r"/shared/(?:album|gallery)/([A-Za-z0-9_-]+)/?", parsed.path)
    if not match:
        return None
    return match.group(1)


def field_value(fields: dict[str, Any], name: str, default: Any = None) -> Any:
    field = fields.get(name)
    return field.get("value", default) if isinstance(field, dict) else default


def cloudkit_timestamp(value: Any) -> str | None:
    try:
        timestamp = float(value) / 1000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def decoded_modern_filename(value: Any) -> str:
    """Public albums currently expose the original filename as base64 bytes."""
    if not isinstance(value, str) or not value:
        return ""
    try:
        return base64.b64decode(value, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


def modern_record_to_item(
    record: dict[str, Any], minimum_long_edge: int, minimum_bytes: int
) -> RemoteItem | None:
    """Convert a public CloudKit CPLMaster record into a dashboard-ready item."""
    if record.get("recordType") != "CPLMaster" or record.get("deleted"):
        return None
    fields = record.get("fields")
    if not isinstance(fields, dict):
        return None
    guid = str(record.get("recordName") or "")
    if not guid:
        return None

    item_type = str(field_value(fields, "itemType", "")).lower()
    is_video = any(token in item_type for token in ("video", "movie", "quicktime", "mpeg"))
    if not is_video and not field_value(fields, "resOriginalRes") and field_value(fields, "resOriginalVidComplRes"):
        is_video = True
    media_type = "video" if is_video else "image"
    prefixes = ("resOriginalVidCompl", "resVidMed", "resVidSmall") if is_video else (
        "resOriginal",
        "resJPEGMed",
        "resJPEGThumb",
    )
    candidates: list[tuple[dict[str, Any], int, int, int, str]] = []
    for prefix in prefixes:
        asset = field_value(fields, f"{prefix}Res")
        if not isinstance(asset, dict) or not isinstance(asset.get("downloadURL"), str):
            continue
        width = as_int(field_value(fields, f"{prefix}Width"))
        height = as_int(field_value(fields, f"{prefix}Height"))
        size = as_int(asset.get("size") or field_value(fields, f"{prefix}FileSize"))
        if max(width, height) < minimum_long_edge or (size and size < minimum_bytes):
            continue
        candidates.append((asset, width, height, size, str(field_value(fields, f"{prefix}FileType", ""))))
    if not candidates:
        return None

    asset, width, height, size, file_type = max(candidates, key=lambda item: (item[1] * item[2], item[3]))
    original_name = decoded_modern_filename(field_value(fields, "filenameEnc"))
    if not original_name:
        extension = ".mp4" if media_type == "video" else ".jpg"
        if "heic" in file_type.lower():
            extension = ".heic"
        original_name = f"icloud-{guid[:12]}{extension}"
    filename = safe_filename(original_name, guid, media_type)
    source_url = str(asset["downloadURL"]).replace("${f}", quote(filename))
    return RemoteItem(
        guid=guid,
        filename=filename,
        source_url=source_url,
        media_type=media_type,
        captured_at=cloudkit_timestamp(field_value(fields, "originalCreationDate") or field_value(fields, "importDate")),
        width=width,
        height=height,
        expected_size=size,
        caption="",
        contributor="",
    )


def select_derivative(
    photo: dict[str, Any], minimum_long_edge: int, minimum_bytes: int
) -> tuple[str, dict[str, Any]] | None:
    derivatives = photo.get("derivatives") or {}
    if not isinstance(derivatives, dict):
        return None
    is_video = str(photo.get("mediaAssetType", "")).lower() == "video"
    candidates: list[tuple[str, dict[str, Any]]] = []
    for name, derivative in derivatives.items():
        if not isinstance(derivative, dict) or not derivative.get("checksum"):
            continue
        lowered = str(name).lower()
        if "poster" in lowered or "thumb" in lowered or "square" in lowered:
            continue
        width = as_int(derivative.get("width"))
        height = as_int(derivative.get("height"))
        size = as_int(derivative.get("fileSize") or derivative.get("size"))
        if max(width, height) < minimum_long_edge:
            continue
        if size and size < minimum_bytes:
            continue
        candidates.append((str(derivative["checksum"]), derivative))

    if not candidates:
        return None
    if is_video:
        return max(candidates, key=lambda item: (as_int(item[1].get("fileSize")), as_int(item[1].get("width")) * as_int(item[1].get("height"))))
    return max(candidates, key=lambda item: (as_int(item[1].get("width")) * as_int(item[1].get("height")), as_int(item[1].get("fileSize"))))


def full_asset_url(asset: dict[str, Any]) -> str:
    path = str(asset.get("url_path") or asset.get("url") or asset.get("URL") or "")
    if path.startswith(("http://", "https://")):
        return path
    location = str(asset.get("url_location") or "")
    if not path or not location:
        raise SyncError("Apple returned an asset without a downloadable location.")
    return f"https://{location}/{path.lstrip('/')}"


class ICloudClient:
    def __init__(self, timeout: int) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "HomeAssistant-iCloud-Shared-Album-Sync/1.0"})

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.session.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            raise SyncError(f"Apple request failed: {error}") from error
        if not isinstance(data, dict):
            raise SyncError("Apple returned an unexpected response.")
        return data

    def _cloudkit_post(
        self, url: str, payload: dict[str, Any], params: dict[str, str]
    ) -> dict[str, Any]:
        """Make a public CloudKit request without ever retaining its short-lived token."""
        try:
            response = self.session.post(
                url,
                data=json.dumps(payload),
                params=params,
                headers={"content-type": "text/plain"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            raise SyncError(f"Apple request failed: {error}") from error
        if not isinstance(data, dict):
            raise SyncError("Apple returned an unexpected response.")
        return data

    def _modern_public_album(
        self, album_id: str, minimum_long_edge: int, minimum_bytes: int
    ) -> list[RemoteItem]:
        common_params = {
            "remapEnums": "true",
            "getCurrentSyncToken": "true",
            "sharing_url_key": album_id,
        }
        resolve_url = (
            f"https://ckdatabasews.icloud.com/database/1/{APPLE_CLOUDKIT_CONTAINER}"
            "/production/public/records/resolve"
        )
        resolved = self._cloudkit_post(
            resolve_url, {"shortGUIDs": [{"value": album_id}]}, common_params
        )
        results = resolved.get("results") or []
        if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
            raise SyncError("Apple could not resolve this public shared album.")
        result = results[0]
        access = result.get("anonymousPublicAccess")
        zone = result.get("zoneID")
        if not isinstance(access, dict) or not isinstance(zone, dict):
            raise SyncError("This public album does not allow anonymous media access.")
        token = str(access.get("token") or "")
        partition = str(access.get("databasePartition") or "")
        parsed_partition = urlparse(partition)
        if (
            not token
            or parsed_partition.scheme != "https"
            or not parsed_partition.hostname
            or not parsed_partition.hostname.endswith(("ckdatabasews.icloud.com", "ckdatabasews.icloud.com.cn"))
        ):
            raise SyncError("Apple returned an invalid public media endpoint.")

        query_url = (
            f"{partition.rstrip('/')}/database/1/{APPLE_CLOUDKIT_CONTAINER}"
            "/production/shared/records/query"
        )
        query_params = {**common_params, "publicAccessAuthToken": token}
        payload: dict[str, Any] = {
            "query": {
                "recordType": "CPLAssetAndMasterByAssetDateWithoutHiddenOrDeleted",
                "filterBy": [
                    {
                        "fieldName": "direction",
                        "comparator": "EQUALS",
                        "fieldValue": {"value": "DESCENDING", "type": "STRING"},
                    }
                ],
            },
            "zoneID": zone,
            "resultsLimit": 100,
        }
        records: list[dict[str, Any]] = []
        seen_markers: set[str] = set()
        while True:
            page = self._cloudkit_post(query_url, payload, query_params)
            page_records = page.get("records") or []
            if not isinstance(page_records, list):
                raise SyncError("Apple's album response did not contain a media list.")
            records.extend(record for record in page_records if isinstance(record, dict))
            marker = str(page.get("continuationMarker") or "")
            if not marker or marker in seen_markers:
                break
            seen_markers.add(marker)
            payload["continuationMarker"] = marker

        selected_items = [
            item
            for record in records
            if (item := modern_record_to_item(record, minimum_long_edge, minimum_bytes))
        ]
        logging.info(
            "Apple listed %d usable item(s) from its current public-album format.",
            len(selected_items),
        )
        return selected_items

    def list_album(
        self, shared_url: str, minimum_long_edge: int, minimum_bytes: int
    ) -> list[RemoteItem]:
        modern_album_id = modern_album_id_from_url(shared_url)
        if modern_album_id:
            return self._modern_public_album(modern_album_id, minimum_long_edge, minimum_bytes)
        album_id = album_id_from_url(shared_url)
        payload = {"streamCtag": None}
        base = f"https://{APPLE_BOOTSTRAP_HOST}/{album_id}/sharedstreams"
        stream = self._post(f"{base}/webstream", payload)
        assigned_host = stream.get("X-Apple-MMe-Host")
        if assigned_host:
            base = f"https://{assigned_host}/{album_id}/sharedstreams"
            stream = self._post(f"{base}/webstream", payload)

        photos = stream.get("photos") or []
        if not isinstance(photos, list):
            raise SyncError("Apple's album response did not contain a photo list.")
        if not photos:
            return []
        guids = [photo.get("photoGuid") for photo in photos if photo.get("photoGuid")]
        assets_response = self._post(f"{base}/webasseturls", {"photoGuids": guids})
        asset_urls = assets_response.get("items") or {}
        if not isinstance(asset_urls, dict):
            raise SyncError("Apple's media response did not contain an asset map.")

        selected_items: list[RemoteItem] = []
        rejected = 0
        for photo in photos:
            guid = str(photo.get("photoGuid") or "")
            if not guid:
                continue
            selected = select_derivative(photo, minimum_long_edge, minimum_bytes)
            if not selected:
                rejected += 1
                continue
            checksum, derivative = selected
            asset = asset_urls.get(checksum)
            if not isinstance(asset, dict):
                logging.warning("Skipping %s: Apple did not return its selected asset URL.", guid)
                rejected += 1
                continue
            url = full_asset_url(asset)
            is_video = str(photo.get("mediaAssetType", "")).lower() == "video"
            media_type = "video" if is_video else "image"
            url_name = Path(unquote(urlparse(url).path)).name
            selected_items.append(
                RemoteItem(
                    guid=guid,
                    filename=safe_filename(url_name, guid, media_type),
                    source_url=url,
                    media_type=media_type,
                    captured_at=photo.get("dateCreated") or photo.get("batchDateCreated"),
                    width=as_int(derivative.get("width") or photo.get("width")),
                    height=as_int(derivative.get("height") or photo.get("height")),
                    expected_size=as_int(derivative.get("fileSize")),
                    caption=str(photo.get("caption") or ""),
                    contributor=str(photo.get("contributorFullName") or ""),
                )
            )
        logging.info("Apple listed %d usable item(s); %d derivative(s) were below the configured floor.", len(selected_items), rejected)
        return selected_items


def destination_for(album: dict[str, Any]) -> tuple[Path, str | None, Path]:
    mode = str(album.get("dest_mode") or "media")
    bases = {"config_www": Path("/config/www"), "media": Path("/media"), "share": Path("/share")}
    if mode not in bases:
        raise SyncError(f"Unsupported dest_mode {mode!r}; use config_www, media, or share.")
    subfolder = str(album.get("media_subfolder") or "iCloud").strip("/ ")
    album_subfolder = str(album.get("album_subfolder") or "").strip("/ ")
    if not album_subfolder or album_subfolder in {".", ".."} or "/" in album_subfolder:
        raise SyncError("album_subfolder must be one safe folder name.")
    root = bases[mode] / subfolder if subfolder else bases[mode]
    destination = root / album_subfolder
    public_base = None
    if mode == "config_www":
        relative = destination.relative_to(Path("/config/www")).as_posix()
        public_base = "/local/" + relative
    return destination, public_base, root


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_copy(source: Path, destination: Path) -> None:
    temporary = destination.with_name(destination.name + ".part")
    shutil.copyfile(source, temporary)
    os.replace(temporary, destination)


def read_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    items = data if isinstance(data, list) else data.get("items", []) if isinstance(data, dict) else []
    return {str(item.get("guid")): item for item in items if isinstance(item, dict) and item.get("guid")}


def unique_filenames(items: Iterable[RemoteItem], previous: dict[str, Any], destination: Path) -> dict[str, str]:
    assigned: dict[str, str] = {}
    claimed: set[str] = set()
    for item in items:
        old_name = str(previous.get(item.guid, {}).get("filename") or "")
        candidate = old_name if old_name and (destination / old_name).is_file() else item.filename
        folded = candidate.casefold()
        if folded in claimed:
            stem, suffix = os.path.splitext(candidate)
            candidate = f"{stem}-{item.guid[:8].lower()}{suffix}"
            folded = candidate.casefold()
        claimed.add(folded)
        assigned[item.guid] = candidate
    return assigned


def is_valid_existing(path: Path, expected_size: int, minimum_bytes: int) -> bool:
    try:
        actual = path.stat().st_size
    except OSError:
        return False
    if actual < minimum_bytes:
        return False
    if expected_size and actual != expected_size:
        return False
    return True


def download_item(session: requests.Session, item: RemoteItem, destination: Path, timeout: int, minimum_bytes: int) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    try:
        with session.get(item.source_url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            total = 0
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(128 * 1024):
                    if chunk:
                        handle.write(chunk)
                        total += len(chunk)
        if total < minimum_bytes:
            raise SyncError(f"Downloaded {item.filename} was only {total} bytes.")
        os.replace(temporary, destination)
        return total
    except (requests.RequestException, OSError, SyncError):
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def media_files(destination: Path) -> list[Path]:
    if not destination.exists():
        return []
    return [path for path in destination.iterdir() if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS]


def mirror_media(
    destination: Path, remote_filenames: set[str], protected_filenames: set[str] | None = None
) -> list[str]:
    removed: list[str] = []
    remote_folded = {name.casefold() for name in remote_filenames}
    protected_folded = {name.casefold() for name in (protected_filenames or {"latest.jpg"}) if name}
    for path in media_files(destination):
        if path.name.casefold() not in remote_folded and path.name.casefold() not in protected_folded:
            path.unlink()
            removed.append(path.name)
            logging.info("Removed album item no longer shared: %s", path.name)
    return sorted(removed)


def prune_media(
    destination: Path,
    keep_days: int,
    max_files: int,
    protected_filenames: set[str] | None = None,
) -> list[str]:
    removed: list[str] = []
    protected_folded = {name.casefold() for name in (protected_filenames or {"latest.jpg"}) if name}
    files = [path for path in media_files(destination) if path.name.casefold() not in protected_folded]
    if keep_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
        for path in files:
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if modified < cutoff:
                path.unlink()
                removed.append(path.name)
        files = [path for path in media_files(destination) if path.name.casefold() not in protected_folded]
    if max_files > 0 and len(files) > max_files:
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        for path in files[max_files:]:
            path.unlink()
            removed.append(path.name)
    for name in removed:
        logging.info("Pruned retained media: %s", name)
    return sorted(set(removed))


def public_item_path(public_base: str | None, filename: str) -> str | None:
    if not public_base:
        return None
    from urllib.parse import quote

    return f"{public_base}/{quote(filename)}"


def configured_value(album: dict[str, Any], global_config: dict[str, Any], key: str) -> Any:
    return album[key] if key in album else global_config[key]


def sync_album(album: dict[str, Any], global_config: dict[str, Any]) -> tuple[AlbumResult, Path]:
    name = str(album.get("name") or album.get("album_subfolder") or "Album")
    slug = str(album["album_subfolder"])
    destination, public_base, catalog_root = destination_for(album)
    destination.mkdir(parents=True, exist_ok=True)
    index_filename = str(album.get("index_filename") or "index.json")
    latest_value = album.get("latest_filename", "latest.jpg")
    latest_filename = str(latest_value) if latest_value else None
    index_path = destination / index_filename
    status_path = destination / ".icloud_album_sync.json"

    timeout = as_int(configured_value(album, global_config, "timeout"), 40)
    minimum_bytes = max(0, as_int(configured_value(album, global_config, "minimum_file_size_kb"), 100) * 1024)
    minimum_long_edge = max(0, as_int(configured_value(album, global_config, "minimum_long_edge"), 1280))
    keep_days = max(0, as_int(configured_value(album, global_config, "keep_days"), 0))
    max_files = max(0, as_int(configured_value(album, global_config, "max_files"), 500))
    mirror_missing = parse_bool(configured_value(album, global_config, "mirror_missing"))
    synced_at = utc_now()

    logging.info("Syncing %s into %s", name, destination)
    try:
        client = ICloudClient(timeout)
        remote_items = client.list_album(str(album["shared_url"]), minimum_long_edge, minimum_bytes)
        previous = read_index(index_path)
        filenames = unique_filenames(remote_items, previous, destination)
        local_sizes: dict[str, int] = {}
        failures: list[str] = []

        for item in remote_items:
            filename = filenames[item.guid]
            target = destination / filename
            if is_valid_existing(target, item.expected_size, minimum_bytes):
                local_sizes[item.guid] = target.stat().st_size
                logging.debug("Already current: %s", filename)
                continue
            try:
                local_sizes[item.guid] = download_item(client.session, item, target, timeout, minimum_bytes)
                logging.info("Downloaded: %s", filename)
            except (requests.RequestException, OSError, SyncError) as error:
                failures.append(f"{filename}: {error}")
                logging.error("Failed to download %s: %s", filename, error)

        remote_names = {filenames[item.guid] for item in remote_items}
        protected = {index_filename, latest_filename or "", ".icloud_album_sync.json"}
        if mirror_missing:
            mirror_media(destination, remote_names, protected)
        prune_media(destination, keep_days, max_files, protected)

        indexed_items: list[dict[str, Any]] = []
        for item in remote_items:
            filename = filenames[item.guid]
            target = destination / filename
            if not target.is_file():
                continue
            record = asdict(item)
            record.pop("source_url", None)
            record["filename"] = filename
            record["path"] = public_item_path(public_base, filename)
            record["file_size"] = local_sizes.get(item.guid, target.stat().st_size)
            indexed_items.append(record)
        indexed_items.sort(key=lambda item: item.get("captured_at") or "", reverse=True)

        index_document = {
            "version": 2,
            "album": {"name": name, "slug": slug},
            "generated_at": synced_at,
            "items": indexed_items,
        }
        atomic_write_json(index_path, index_document)

        newest_image = next((item for item in indexed_items if item["media_type"] == "image"), None)
        if latest_filename and newest_image:
            atomic_copy(destination / newest_image["filename"], destination / latest_filename)

        status = "partial" if failures else "ok"
        error_text = "; ".join(failures[:10]) if failures else None
        status_document = {
            "version": 1,
            "album": name,
            "status": status,
            "synced_at": synced_at,
            "remote_items": len(remote_items),
            "indexed_items": len(indexed_items),
            "errors": failures[:10],
        }
        atomic_write_json(status_path, status_document)
        return (
            AlbumResult(
                name=name,
                slug=slug,
                destination=destination,
                public_base=public_base,
                index_filename=index_filename,
                latest_filename=latest_filename,
                item_count=len(indexed_items),
                status=status,
                synced_at=synced_at,
                error=error_text,
            ),
            catalog_root,
        )
    except (OSError, SyncError, ValueError) as error:
        logging.error("Album %s failed: %s", name, error)
        atomic_write_json(
            status_path,
            {"version": 1, "album": name, "status": "error", "synced_at": synced_at, "error": str(error)},
        )
        previous_count = len(read_index(index_path))
        return (
            AlbumResult(
                name=name,
                slug=slug,
                destination=destination,
                public_base=public_base,
                index_filename=index_filename,
                latest_filename=latest_filename,
                item_count=previous_count,
                status="error",
                synced_at=synced_at,
                error=str(error),
            ),
            catalog_root,
        )


def write_catalogs(results: list[tuple[AlbumResult, Path]], filename: str) -> None:
    grouped: dict[Path, list[AlbumResult]] = {}
    for result, root in results:
        grouped.setdefault(root, []).append(result)
    for root, albums in grouped.items():
        entries = []
        for album in sorted(albums, key=lambda item: item.name.casefold()):
            index_path = f"{album.public_base}/{album.index_filename}" if album.public_base else str(album.destination / album.index_filename)
            latest_path = (
                f"{album.public_base}/{album.latest_filename}"
                if album.public_base and album.latest_filename
                else str(album.destination / album.latest_filename)
                if album.latest_filename
                else None
            )
            entries.append(
                {
                    "name": album.name,
                    "slug": album.slug,
                    "status": album.status,
                    "item_count": album.item_count,
                    "synced_at": album.synced_at,
                    "index": index_path,
                    "latest": latest_path,
                    "error": album.error,
                }
            )
        atomic_write_json(root / filename, {"version": 1, "generated_at": utc_now(), "albums": entries})
        logging.info("Updated album catalog: %s", root / filename)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--albums", required=True)
    parser.add_argument("--interval-minutes", type=int, default=180)
    parser.add_argument("--timeout", type=int, default=40)
    parser.add_argument("--keep-days", type=int, default=0)
    parser.add_argument("--max-files", type=int, default=500)
    parser.add_argument("--mirror-missing", type=parse_bool, default=True)
    parser.add_argument("--minimum-file-size-kb", type=int, default=100)
    parser.add_argument("--minimum-long-edge", type=int, default=1280)
    parser.add_argument("--catalog-filename", default="albums.json")
    parser.add_argument("--debug", type=parse_bool, default=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.debug)
    try:
        albums = parse_albums(args.albums)
    except SyncError as error:
        logging.error("%s", error)
        return 2
    global_config = vars(args)
    results = [sync_album(album, global_config) for album in albums]
    try:
        write_catalogs(results, args.catalog_filename)
    except OSError as error:
        logging.error("Could not update the album catalog: %s", error)
        return 2
    failed = [result for result, _ in results if result.status == "error"]
    partial = [result for result, _ in results if result.status == "partial"]
    logging.info(
        "Sync finished: %d album(s), %d failed, %d partial.",
        len(results),
        len(failed),
        len(partial),
    )
    return 2 if failed else 1 if partial else 0


if __name__ == "__main__":
    sys.exit(main())
