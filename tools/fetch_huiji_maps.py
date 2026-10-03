"""Inventory Forgetting Arc chapter 1-9 maps via the Huiji MediaWiki API.

Run: python tools/fetch_huiji_maps.py --out resource/reference_maps
     python tools/fetch_huiji_maps.py --out resource/reference_maps --download
"""

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests


API = "https://morimens.huijiwiki.com/api.php"
PATTERN = re.compile(r"^忘却篇([1-9])-([0-9]+)_map\.(jpg|jpeg|png)$", re.I)


def list_images(session: requests.Session) -> list[dict]:
    params = {
        "action": "query", "list": "allimages", "aiprefix": "忘却篇",
        "aisort": "name", "ailimit": "500", "aiprop": "url|size|timestamp|sha1",
        "format": "json", "formatversion": "2",
    }
    images = []
    while True:
        response = session.get(API, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise RuntimeError(data["error"])
        images.extend(data["query"]["allimages"])
        continuation = data.get("continue")
        if not continuation:
            return images
        params.update(continuation)


def collect(session: requests.Session) -> list[dict]:
    records = []
    for image in list_images(session):
        match = PATTERN.fullmatch(image["name"])
        if not match:
            continue
        chapter, stage, extension = match.groups()
        records.append({
            "chapter": int(chapter), "stage": int(stage), "name": image["name"],
            "wiki_page": image.get("descriptionurl"), "image_url": image.get("url"),
            "size_bytes": image.get("size"), "width": image.get("width"),
            "height": image.get("height"), "sha1": image.get("sha1"),
            "wiki_timestamp": image.get("timestamp"), "extension": extension.lower(),
        })
    return sorted(records, key=lambda r: (r["chapter"], r["stage"], r["name"]))


def download(session: requests.Session, records: list[dict], folder: Path, delay: float) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for record in records:
        path = folder / f"{record['chapter']}-{record['stage']}.{record['extension']}"
        if path.exists() and record.get("sha1"):
            if hashlib.sha1(path.read_bytes()).hexdigest() == record["sha1"]:
                record["download"] = "existing"
                record["local_file"] = str(path)
                continue
        try:
            response = session.get(record["image_url"], timeout=30)
            # Huiji's HTTPS CDN can return 567 while the same object is served
            # over HTTP. Trust bytes only after verifying the HTTPS API's SHA-1.
            if response.status_code == 567 and record["image_url"].startswith(
                "https://huiji-public.huijistatic.com/"
            ):
                response = session.get("http://" + record["image_url"][8:], timeout=30)
                record["download_transport"] = "http_fallback_after_https_567"
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            data = response.content
            if not content_type.startswith("image/") or len(data) < 1000:
                raise ValueError(f"unexpected response: {content_type}, {len(data)} bytes")
            if record.get("sha1") and hashlib.sha1(data).hexdigest() != record["sha1"]:
                raise ValueError("image SHA-1 differs from wiki metadata")
            path.write_bytes(data)
            record["download"] = "ok"
            record["local_file"] = str(path)
        except (requests.RequestException, ValueError) as exc:
            record["download"] = "failed"
            record["download_error"] = str(exc)
        time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("resource/reference_maps"))
    parser.add_argument("--download", action="store_true", help="also fetch image bytes")
    parser.add_argument("--delay", type=float, default=0.3, help="seconds between image requests")
    args = parser.parse_args()
    with requests.Session() as session:
        session.headers.update({"User-Agent": "MMA-5771-map-research/1.0 (MediaWiki public API)"})
        records = collect(session)
        if args.download:
            download(session, records, args.out / "images", max(0, args.delay))
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source": API, "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "scope": "忘却篇第1至9章；仅 *_map.jpg/png 文件",
        "counts_by_chapter": {str(i): sum(r["chapter"] == i for r in records) for i in range(1, 10)},
        "maps": records,
    }
    path = args.out / "huiji_maps_1-9.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(path), "count": len(records), "counts_by_chapter": manifest["counts_by_chapter"], "downloaded": sum(r.get("download") == "ok" for r in records), "failed": sum(r.get("download") == "failed" for r in records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
