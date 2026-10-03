"""Collect battle-map images for 意识潜游 / 特遣记录 / 异梦视界 from the Huiji wiki.

Run on a machine whose browser can open morimens.huijiwiki.com (the cloud sandbox is
blocked by Cloudflare). Typical use:

    pip install requests
    python tools/fetch_huiji_special_maps.py --out resource/reference_maps_special --download

If the API answers with a Cloudflare challenge, open the wiki in a browser, copy the
``cf_clearance`` cookie and the browser User-Agent, then:

    python tools/fetch_huiji_special_maps.py --download \
        --cookie "cf_clearance=XXXX" --user-agent "<your browser UA>"

For each wiki page the script records the page wikitext, every file it embeds, and follows links (default: titles ending in -NN such as 蔷薇礼赞-01, see --follow/--depth) plus "页面/子页"-style sub-pages.
It then resolves image URL/size/sha1 and (with --download) saves the files whose name matches
--filter (default: names ending in _map.jpg/png, e.g. 蔷薇礼赞01_map.jpg). Use --all-images to download every embedded file.
Pages that do not exist (e.g. the 异梦视界 red link) are reported, not fatal; use
--image-prefix to also pull files by file-name prefix (e.g. --image-prefix 异梦视界).
"""

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

API = "https://morimens.huijiwiki.com/api.php"
DEFAULT_PAGES = ["意识潜游", "特遣记录", "异梦视界"]
DEFAULT_FILTER = r"_map\.(jpe?g|png)$"


class Wiki:
    def __init__(self, args):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": args.user_agent
            or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        if args.cookie:
            self.s.headers["Cookie"] = args.cookie
        if args.proxy:
            self.s.proxies = {"http": args.proxy, "https": args.proxy}
        self.delay = args.delay

    def api(self, **params):
        params.update(format="json", formatversion="2")
        r = self.s.get(API, params=params, timeout=30)
        if "json" not in r.headers.get("content-type", "") or r.text.lstrip().startswith("<"):
            raise SystemExit(
                f"API returned non-JSON (HTTP {r.status_code}) - probably a Cloudflare "
                "challenge. Pass --cookie cf_clearance=... and --user-agent from your browser.")
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(data["error"])
        time.sleep(self.delay)
        return data


def parse_page(wiki, title):
    try:
        data = wiki.api(action="parse", page=title, prop="images|links|wikitext|sections",
                        redirects="1")
    except RuntimeError as exc:
        return {"title": title, "missing": True, "error": str(exc)}
    p = data["parse"]
    return {
        "title": p["title"], "missing": False, "images": p.get("images", []),
        "links": [l["title"] for l in p.get("links", [])
                  if l.get("ns") == 0 and l.get("exists", True)],
        "sections": [s.get("line") for s in p.get("sections", [])],
        "wikitext": p.get("wikitext", ""),
    }


def subpage_titles(wiki, title):
    out = []
    params = dict(action="query", list="allpages", apprefix=title + "/", aplimit="500")
    while True:
        data = wiki.api(**params)
        out += [p["title"] for p in data["query"]["allpages"]]
        if "continue" not in data:
            return out
        params.update(data["continue"])


def images_by_prefix(wiki, prefix):
    params = dict(action="query", list="allimages", aiprefix=prefix, ailimit="500",
                  aisort="name", aiprop="url|size|sha1|timestamp")
    out = []
    while True:
        data = wiki.api(**params)
        out += data["query"]["allimages"]
        if "continue" not in data:
            return out
        params.update(data["continue"])


def image_info(wiki, names):
    info = {}
    names = sorted(set(names))
    for i in range(0, len(names), 40):
        chunk = names[i:i + 40]
        data = wiki.api(action="query", prop="imageinfo", iiprop="url|size|sha1|timestamp",
                        titles="|".join("File:" + n for n in chunk))
        for page in data["query"]["pages"]:
            ii = (page.get("imageinfo") or [None])[0]
            if ii:
                info[page["title"].split(":", 1)[1].replace(" ", "_")] = ii
    return info


def safe(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def download(wiki, rec, folder):
    path = folder / safe(rec["name"])
    if path.exists() and rec.get("sha1") and hashlib.sha1(path.read_bytes()).hexdigest() == rec["sha1"]:
        rec["download"] = "existing"
        return
    try:
        r = wiki.s.get(rec["image_url"], timeout=60)
        if r.status_code == 567 and rec["image_url"].startswith("https://"):
            r = wiki.s.get("http://" + rec["image_url"][8:], timeout=60)  # Huiji CDN quirk
        r.raise_for_status()
        data = r.content
        if not r.headers.get("content-type", "").startswith("image/") or len(data) < 1000:
            raise ValueError("unexpected response")
        if rec.get("sha1") and hashlib.sha1(data).hexdigest() != rec["sha1"]:
            raise ValueError("sha1 mismatch")
        path.write_bytes(data)
        rec["download"] = "ok"
        rec["local_file"] = str(path)
    except (requests.RequestException, ValueError) as exc:
        rec["download"] = "failed"
        rec["download_error"] = str(exc)
    time.sleep(wiki.delay)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("resource/reference_maps_special"))
    ap.add_argument("--page", action="append", help="wiki page title (repeatable)")
    ap.add_argument("--image-prefix", action="append", default=[], help="also list files by name prefix")
    ap.add_argument("--filter", default=DEFAULT_FILTER, help="regex on file name to download")
    ap.add_argument("--all-images", action="store_true", help="ignore --filter")
    ap.add_argument("--depth", type=int, default=2, help="how many link levels to follow from each --page")
    ap.add_argument("--follow", default=r"-\d+(·.+)?$", help="regex: link titles to follow (default: stage pages like 蔷薇礼赞-01 and their event pages like 终末交响曲-02·剧情)")
    ap.add_argument("--no-subpages", action="store_true", help="do not follow linked sub-pages")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--cookie")
    ap.add_argument("--user-agent")
    ap.add_argument("--proxy")
    ap.add_argument("--delay", type=float, default=0.4)
    args = ap.parse_args()

    wiki = Wiki(args)
    pages, seen = {}, set()
    follow = re.compile(args.follow)
    queue = [(t, None, 0) for t in (args.page or DEFAULT_PAGES)]
    while queue:
        title, parent, depth = queue.pop(0)
        if title in seen:
            continue
        seen.add(title)
        page = parse_page(wiki, title)
        page["parent"], page["depth"] = parent, depth
        pages[title] = page
        if page["missing"]:
            print(f"MISSING {title}")
            continue
        print(f"ok d{depth} {title}: {len(page['images'])} images, {len(page['links'])} links")
        if depth >= args.depth:
            continue
        cands = {l for l in page["links"] if follow.search(l)}
        if not args.no_subpages:
            cands |= set(subpage_titles(wiki, title))
        for sub in sorted(cands):
            queue.append((sub, title, depth + 1))

    files = {}  # name -> set(pages)
    for t, p in pages.items():
        for n in p.get("images", []):
            files.setdefault(n.replace(" ", "_"), set()).add(t)
    extra = []
    for prefix in args.image_prefix:
        for img in images_by_prefix(wiki, prefix):
            files.setdefault(img["name"], set())
            extra.append(img)
    info = image_info(wiki, files)
    for img in extra:
        info.setdefault(img["name"], img)

    pat = re.compile(args.filter, re.I)
    records = []
    for name in sorted(files):
        ii = info.get(name)
        if not ii:
            continue
        records.append({
            "name": name, "pages": sorted(files[name]), "image_url": ii.get("url"),
            "width": ii.get("width"), "height": ii.get("height"), "size_bytes": ii.get("size"),
            "sha1": ii.get("sha1"), "wiki_timestamp": ii.get("timestamp"),
            "selected": args.all_images or bool(pat.search(name)),
        })

    args.out.mkdir(parents=True, exist_ok=True)
    if args.download:
        folder = args.out / "images"
        folder.mkdir(exist_ok=True)
        for rec in records:
            if rec["selected"] and rec["image_url"]:
                download(wiki, rec, folder)
    (args.out / "pages").mkdir(exist_ok=True)
    for t, p in pages.items():
        (args.out / "pages" / (safe(t) + ".json")).write_text(
            json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "source": API, "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "pages": {t: {"missing": p["missing"], "parent": p["parent"], "depth": p.get("depth"), "image_count": len(p.get("images", []))}
                  for t, p in pages.items()},
        "files": records,
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if not any(r["selected"] for r in records):
        print("No file matched --filter. Sample file names (use --all-images or adjust --filter):")
        for r in records[:15]:
            print("   ", r["name"])
    print(json.dumps({
        "pages": len(pages), "missing_pages": [t for t, p in pages.items() if p["missing"]],
        "files": len(records), "selected": sum(r["selected"] for r in records),
        "downloaded": sum(r.get("download") == "ok" for r in records),
        "failed": sum(r.get("download") == "failed" for r in records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
