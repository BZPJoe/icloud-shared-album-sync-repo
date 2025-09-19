#!/usr/bin/env python3

import argparse
import os
import yaml
import requests
import json
from datetime import datetime, timedelta
import logging
import re
from typing import List, Tuple, Dict, Any, Optional

# =========================
# HARD GUARANTEES: NO THUMBNAILS
# =========================
# Raise/lower these if needed:
MIN_LONG_EDGE = 2000          # require at least this many pixels on the long side
MIN_FILESIZE_BYTES = 300 * 1024  # require at least this many bytes (if size known)

# =========================
# Logging
# =========================
def setup_logging(debug: bool) -> None:
    level = logging.INFO
    if debug:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(asctime)s - %(levelname)s - %(message)s")


# =========================
# Single-line YAML normalizer
# =========================
KEY_PATTERN = re.compile(r'(?<![\w-])([A-Za-z_][\w-]*)\s*:', re.U)

def _find_key_spans(s: str) -> List[Tuple[str, int, int]]:
    spans: List[Tuple[str, int, int]] = []
    for match in KEY_PATTERN.finditer(s):
        key = match.group(1)
        spans.append((key, match.start(1), match.end()))
    return spans

def normalize_single_line_yaml(albums_str: str) -> str:
    s = albums_str.strip()
    if '\n' in s and re.search(r'^\s*-\s+', s, re.M):
        return s
    if not s.startswith('- '):
        s = '- ' + s
    body = s[2:]
    spans = _find_key_spans(body)
    if not spans:
        return s
    lines: List[str] = []
    for i, (key, start, colon_pos) in enumerate(spans):
        next_start = len(body) if i + 1 == len(spans) else spans[i + 1][1]
        raw_val = body[colon_pos:next_start].lstrip().rstrip()
        if i == 0:
            lines.append(f"- {key}: {raw_val}" if raw_val else f"- {key}:")
        else:
            lines.append(f"  {key}: {raw_val}" if raw_val else f"  {key}:")
    return "\n".join(lines)


# =========================
# Full-res URL selection (strict)
# =========================
THUMB_HINTS = ("thumb", "thumbnail", "square", "poster", "preview", "small", "mini", "tile", "low", "tiny")
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".hevc")
DIM_IN_KEY = re.compile(r'(\d+)[xX](\d+)')  # e.g., R4032x3024 or 3840x2160

PREFERRED_ORIGINAL_KEYS = (
    "resoriginal", "original", "resjpegfull", "fullres", "master", "resfull", "publicsharegenericlarge"
)

def _is_thumbish_name(name: str) -> bool:
    low = (name or "").lower()
    return any(h in low for h in THUMB_HINTS)

def _full_url(location: Optional[str], path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if location:
        if not path.startswith('/'):
            path = '/' + path
        return f"https://{location}{path}"
    return path

def _get_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default

def _dimensions_from_key(key: str) -> Tuple[int, int]:
    m = DIM_IN_KEY.search(key or "")
    if m:
        return _get_int(m.group(1)), _get_int(m.group(2))
    return 0, 0

def _candidate_from_derivative(k: str, v: Dict[str, Any], location: Optional[str]) -> Optional[Dict[str, Any]]:
    url = v.get("url") or v.get("URL")
    if not url:
        return None
    url_full = _full_url(location, url)

    # Reject anything hinting at thumbs via key/type/filename/url
    fname = (v.get("fileName") or v.get("filename") or "")
    dtype = (v.get("derivativeType") or v.get("type") or "")
    if _is_thumbish_name(k) or _is_thumbish_name(fname) or _is_thumbish_name(dtype) or _is_thumbish_name(url_full):
        return None

    w = _get_int(v.get("width") or v.get("W"))
    h = _get_int(v.get("height") or v.get("H"))
    if not (w and h):
        # Derive from key when possible
        k_w, k_h = _dimensions_from_key(k or "")
        if k_w and k_h:
            w, h = k_w, k_h

    size = _get_int(v.get("fileSize") or v.get("size"))
    return {"url": url_full, "w": w, "h": h, "key": k, "size": size}

def _meets_fullsize_floor(c: Dict[str, Any]) -> bool:
    long_edge = max(c.get("w", 0), c.get("h", 0))
    size = c.get("size", 0)
    # Allow videos even if dimension unknown, but still apply file size floor if available
    is_video = any(c["url"].lower().endswith(ext) for ext in VIDEO_EXTS)
    if is_video:
        return size == 0 or size >= MIN_FILESIZE_BYTES
    # For photos, require both long-edge and (if known) file size
    if long_edge < MIN_LONG_EDGE:
        return False
    if size and size < MIN_FILESIZE_BYTES:
        return False
    return True

def pick_best_download_url_from_asset(asset: Dict[str, Any]) -> Optional[str]:
    location = asset.get("url_location")
    derivatives = asset.get("derivatives") or {}

    candidates: List[Dict[str, Any]] = []
    if isinstance(derivatives, dict):
        for k, v in derivatives.items():
            if isinstance(v, dict):
                cand = _candidate_from_derivative(k, v, location)
                if cand:
                    candidates.append(cand)

    # 1) Prefer explicit originals if they meet the floor
    for pref in PREFERRED_ORIGINAL_KEYS:
        for c in candidates:
            if c["key"] and c["key"].lower() == pref and _meets_fullsize_floor(c):
                return c["url"]

    # 2) Otherwise choose the largest derivative that meets the fullsize floor
    fullsize_ok = [c for c in candidates if _meets_fullsize_floor(c)]
    if fullsize_ok:
        best = max(fullsize_ok, key=lambda x: (x["w"] * x["h"], x["size"]))
        return best["url"]

    # 3) As a final attempt, try the asset's original path *only if* it doesn't look thumb-ish.
    path = asset.get("url_path")
    if path and not _is_thumbish_name(path):
        # We cannot know dimensions here; require at least size floor if response provides Content-Length later.
        # We'll handle that in the downloader by aborting small files.
        return _full_url(location, path)

    # 4) Otherwise, reject this asset entirely (do not download thumbnails).
    return None


# =========================
# Fetch media list from iCloud Shared Album
# =========================
def fetch_album_media(shared_url: str, timeout: int) -> List[str]:
    try:
        if '#' not in shared_url:
            logging.error("Shared URL missing album ID fragment (#...).")
            return []
        album_id = shared_url.split('#')[-1]
        base_api_url = f"https://p23-sharedstreams.icloud.com/{album_id}/sharedstreams"

        payload = {"streamCtag": None}
        r = requests.post(f"{base_api_url}/webstream", json=payload, timeout=timeout)
        r.raise_for_status()
        stream_data = r.json()

        host = stream_data.get("X-Apple-MMe-Host")
        if host:
            base_api_url = f"https://{host}/{album_id}/sharedstreams"
            r = requests.post(f"{base_api_url}/webstream", json=payload, timeout=timeout)
            r.raise_for_status()
            stream_data = r.json()

        photo_guids = [p.get("photoGuid") for p in stream_data.get("photos", []) if p.get("photoGuid")]
        if not photo_guids:
            logging.info("No photos listed in stream.")
            return []

        r = requests.post(f"{base_api_url}/webasseturls", json={"photoGuids": photo_guids}, timeout=timeout)
        r.raise_for_status()
        items = r.json().get("items", {}) or {}

        media_urls: List[str] = []
        for guid, asset in items.items():
            url = pick_best_download_url_from_asset(asset)
            if url:
                media_urls.append(url)
                logging.debug("Selected media for %s: %s", guid, url)
            else:
                logging.warning("Skipping asset %s: no full-size candidate met the floor.", guid)

        if not media_urls:
            logging.warning("No valid media URLs found (all failed full-size checks).")
        return media_urls

    except requests.RequestException as e:
        logging.error("Error fetching album media: %s", e)
        return []


# =========================
# Download, prune, mirror
# =========================
def _content_length(resp: requests.Response) -> int:
    try:
        return int(resp.headers.get("Content-Length", "0"))
    except Exception:
        return 0

def download_file(url: str, dest_dir: str, index_filename: Optional[str], timeout: int = 40) -> bool:
    try:
        os.makedirs(dest_dir, exist_ok=True)

        # HEAD first to enforce filesize floor when we don't know dims (e.g., url_path fallback)
        try:
            head = requests.head(url, timeout=timeout, allow_redirects=True)
            if head.ok:
                cl = _content_length(head)
                if cl and cl < MIN_FILESIZE_BYTES:
                    logging.warning("Rejecting likely thumbnail (too small: %d bytes): %s", cl, url)
                    return False
        except requests.RequestException:
            # If HEAD fails, we'll still GET but will double-check size while streaming
            pass

        resp = requests.get(url, stream=True, timeout=timeout)
        resp.raise_for_status()

        cd = resp.headers.get("Content-Disposition", "")
        m = re.search(r'filename\*?=([^;]+)', cd)
        if m:
            raw = m.group(1).strip().strip('"')
            filename = os.path.basename(raw)
        else:
            filename = os.path.basename(url.split('?')[0])

        path = os.path.join(dest_dir, filename)

        # Stream to temp file first, enforce filesize floor
        tmp_path = path + ".part"
        total_bytes = 0
        with open(tmp_path, 'wb') as f:
            for chunk in resp.iter_content(8192):
                if chunk:
                    f.write(chunk)
                    total_bytes += len(chunk)

        if total_bytes < MIN_FILESIZE_BYTES:
            # Too small (likely a thumbnail); do not keep it.
            try:
                os.remove(tmp_path)
            except FileNotFoundError:
                pass
            logging.warning("Rejecting likely thumbnail after download (size=%d): %s", total_bytes, url)
            return False

        os.replace(tmp_path, path)
        logging.info("Downloaded: %s (%d bytes)", filename, total_bytes)

        # Update index.json
        if index_filename:
            index_path = os.path.join(dest_dir, index_filename)
            try:
                idx = []
                if os.path.exists(index_path):
                    with open(index_path, 'r', encoding='utf-8') as fh:
                        idx = json.load(fh)
                idx.insert(0, {
                    "filename": filename,
                    "downloaded_at": datetime.utcnow().isoformat() + "Z",
                    "url": url
                })
                with open(index_path, 'w', encoding='utf-8') as fh:
                    json.dump(idx, fh, ensure_ascii=False, indent=2)
                logging.debug("Updated %s with %s", index_filename, filename)
            except Exception as e:
                logging.warning("Failed to update %s: %s", index_filename, e)

        return True

    except requests.RequestException as e:
        logging.error("Failed to download %s: %s", url, e)
        return False

def prune_files(dest_dir: str, keep_days: int, max_files: int) -> None:
    try:
        files = [(f, os.path.getmtime(os.path.join(dest_dir, f))) for f in os.listdir(dest_dir)]
    except FileNotFoundError:
        return

    files.sort(key=lambda x: x[1], reverse=True)

    if keep_days > 0:
        cutoff = datetime.now() - timedelta(days=keep_days)
        for f, mtime in files:
            if datetime.fromtimestamp(mtime) < cutoff:
                os.remove(os.path.join(dest_dir, f))
                logging.info("Pruned by age: %s", f)

    try:
        files = [(f, os.path.getmtime(os.path.join(dest_dir, f))) for f in os.listdir(dest_dir)]
    except FileNotFoundError:
        return
    files.sort(key=lambda x: x[1], reverse=True)

    if max_files > 0 and len(files) > max_files:
        for f, _ in files[max_files:]:
            os.remove(os.path.join(dest_dir, f))
            logging.info("Pruned by count: %s", f)

def mirror_missing_files(dest_dir: str, current_filenames: List[str]) -> None:
    try:
        existing = set(os.listdir(dest_dir))
    except FileNotFoundError:
        return
    to_delete = existing - set(current_filenames)
    for f in to_delete:
        try:
            os.remove(os.path.join(dest_dir, f))
            logging.info("Mirrored deletion: %s", f)
        except Exception as e:
            logging.warning("Failed to delete %s: %s", f, e)


# =========================
# Destination path
# =========================
def resolve_dest_dir(dest_mode: str, media_subfolder: Optional[str], album_subfolder: Optional[str]) -> str:
    if dest_mode == 'media':
        base = '/media'
    elif dest_mode == 'share':
        base = '/share'
    elif dest_mode == 'config_www':
        base = '/config/www'
    else:
        base = '/media'
    parts = [base]
    if media_subfolder:
        parts.append(media_subfolder)
    if album_subfolder:
        parts.append(album_subfolder)
    return os.path.join(*parts)


# =========================
# Sync one album
# =========================
def sync_album(album_cfg: Dict[str, Any], global_cfg: Dict[str, Any]) -> None:
    shared_url = album_cfg.get('shared_url')
    dest_mode = album_cfg.get('dest_mode', 'media')
    media_subfolder = album_cfg.get('media_subfolder', 'iCloud')
    album_subfolder = album_cfg.get('album_subfolder')
    index_filename = album_cfg.get('index_filename', 'index.json')

    if not shared_url or not album_subfolder:
        logging.error("Album missing required keys: shared_url or album_subfolder")
        return

    timeout = global_cfg.get('timeout', 40)
    keep_days = global_cfg.get('keep_days', 0)
    max_files = global_cfg.get('max_files', 500)
    mirror_missing = global_cfg.get('mirror_missing', False)

    dest_dir = resolve_dest_dir(dest_mode, media_subfolder, album_subfolder)
    os.makedirs(dest_dir, exist_ok=True)
    logging.info("Syncing to %s", dest_dir)

    media_urls = fetch_album_media(shared_url, timeout)
    if not media_urls:
        logging.warning("No media found to download.")
        return

    downloaded_filenames: List[str] = []
    for url in media_urls:
        if download_file(url, dest_dir, index_filename=index_filename, timeout=timeout):
            filename = os.path.basename(url.split('?')[0])
            downloaded_filenames.append(filename)

    prune_files(dest_dir, keep_days, max_files)

    if mirror_missing:
        try:
            current_on_disk = [f for f in os.listdir(dest_dir) if os.path.isfile(os.path.join(dest_dir, f))]
        except FileNotFoundError:
            current_on_disk = []
        mirror_missing_files(dest_dir, current_on_disk if not downloaded_filenames else downloaded_filenames)


# =========================
# Main
# =========================
def main() -> None:
    parser = argparse.ArgumentParser(description="iCloud Shared Album Sync")
    parser.add_argument('--keep-days', type=int, default=0)
    parser.add_argument('--max-files', type=int, default=500)
    parser.add_argument('--timeout', type=int, default=40)
    parser.add_argument('--debug', type=lambda s: str(s).lower() in ('1','true','yes','on'), default=False)
    parser.add_argument('--mirror-missing', type=bool, default=True)
    parser.add_argument('--albums', type=str, required=True)
    args = parser.parse_args()

    setup_logging(args.debug)

    global_config = {
        'keep_days': args.keep_days,
        'max_files': args.max_files,
        'timeout': args.timeout,
        'mirror_missing': args.mirror_missing
    }

    albums_str = args.albums.strip()
    if '\n' not in albums_str:
        logging.info("Detected single-line albums input; normalizing to multiline YAML")
        albums_str = normalize_single_line_yaml(albums_str)

    try:
        albums = yaml.safe_load(albums_str)
        if not isinstance(albums, list):
            albums = [albums] if albums else []
    except yaml.YAMLError as e:
        logging.error("Invalid albums YAML after normalization: %s", e)
        logging.error("Raw input: %s", args.albums)
        return

    if not albums:
        logging.warning("No valid albums configured. Skipping sync.")
        return

    for album in albums:
        if 'shared_url' not in album or 'album_subfolder' not in album:
            logging.error("Skipping album %s: Missing required fields", album.get('name', 'Unnamed'))
            continue
        sync_album(album, global_config)

if __name__ == '__main__':
    main()
