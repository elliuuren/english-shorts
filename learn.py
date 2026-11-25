"""The channel's weekly learning step. Reads how each video did on YouTube, works out which styles / hooks / series / lengths
beat the channel's own average, and writes learned.json. main.py reads that file to pick styles and topics more wisely.
It changes NO code - only that small file - and main.py always keeps about a quarter of videos random so it keeps testing new things.

Needs one secret: YT_API_KEY (a plain YouTube Data API key). Optional: YT_CHANNEL_ID, or YT_HANDLE (default ElliuurenEnglish)."""
import json
import math
import os
import re
import statistics
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HISTORY, LEARNED, STATS = ROOT / "history.json", ROOT / "learned.json", ROOT / "stats.json"
API = "https://www.googleapis.com/youtube/v3"
MIN_AGE_DAYS = 3      # a video younger than this has not had its chance yet
MIN_N = 3             # a style needs at least this many videos before it is trusted
ATTRS = ("mode", "hook_style", "series", "grade", "style", "length")


def norm(t):
    return re.sub(r"[^a-z0-9]+", " ", str(t).lower()).strip()


# ------------------------------------------------------------------ YouTube (public data, API key only)
def _get(path, **params):
    import requests
    r = requests.get(f"{API}/{path}", params={**params, "key": os.environ["YT_API_KEY"]}, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_uploads():
    cid = os.getenv("YT_CHANNEL_ID", "").strip()
    if cid:
        items = _get("channels", part="contentDetails", id=cid).get("items") or []
    else:
        handle = "@" + os.getenv("YT_HANDLE", "ElliuurenEnglish").lstrip("@")
        items = _get("channels", part="contentDetails", forHandle=handle).get("items") or []
    if not items:
        raise RuntimeError("channel not found: set the YT_CHANNEL_ID secret (YouTube Studio > Settings > Channel > Advanced settings)")
    playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    out, token = [], None
    while len(out) < 600:
        params = {"part": "snippet", "playlistId": playlist, "maxResults": 50}
        if token:
            params["pageToken"] = token
        d = _get("playlistItems", **params)
        for it in d.get("items", []):
            sn = it["snippet"]
            out.append({"id": sn["resourceId"]["videoId"], "title": sn["title"], "published": sn["publishedAt"]})
        token = d.get("nextPageToken")
        if not token:
            break
    return out


def fetch_stats(ids):
    out = {}
    for i in range(0, len(ids), 50):
        d = _get("videos", part="statistics", id=",".join(ids[i:i + 50]))
        for it in d.get("items", []):
            s = it.get("statistics", {})
            out[it["id"]] = {"views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)), "comments": int(s.get("commentCount", 0))}
    return out


# ------------------------------------------------------------------ the learning itself (pure functions, easy to test)
def attach_ids(history, uploads):
    """older history entries have no video id: match them to the channel's uploads by title"""
    have = {h.get("video_id") for h in history if h.get("video_id")}
    by_title = {}
    for u in uploads:
        by_title.setdefault(norm(u["title"]), []).append(u)
    n = 0
    for h in history:
        if h.get("video_id"):
            continue
        for u in by_title.get(norm(h.get("title", "")), []):
            if u["id"] not in have:
                h["video_id"] = u["id"]
                h["published"] = u["published"]
                have.add(u["id"])
                n += 1
                break
    return n


def length_bucket(h):
    s = h.get("secs")
    if not s:
        return ""
    return "under 15s" if s < 15 else "15-30s" if s < 30 else "30s+"


def score_rows(history, stats, now=None):
    now = now or datetime.now(timezone.utc)
    rows = []
    for h in history:
        vid = h.get("video_id")
        if not vid or vid not in stats:
            continue
        pub = h.get("published")
        try:
            age = (now - datetime.fromisoformat(pub.replace("Z", "+00:00"))).total_seconds() / 86400 if pub else None
        except Exception:
            age = None
        if age is None and h.get("date"):
            age = (now.date() - date.fromisoformat(h["date"])).days
        if age is None or age < MIN_AGE_DAYS:
            continue
        s = stats[vid]
        rows.append({**h, "length": length_bucket(h), "views": s["views"], "likes": s["likes"], "comments": s["comments"], "age": age})
    if not rows:
        return rows
    med = statistics.median(r["views"] for r in rows)
    for r in rows:
        r["score"] = (r["views"] + 5) / (med + 5)  # 1.0 = a typical video for this channel
    return rows


def weights_from(rows):
    out = {}
    for a in ATTRS:
        groups = {}
        for r in rows:
            v = str(r.get(a) or "").strip()
            if v:
                groups.setdefault(v, []).append(math.log(r["score"]))
        w = {}
        for v, logs in groups.items():
            n = len(logs)
            if n < MIN_N:
                continue
            m = (sum(logs) / n) * n / (n + MIN_N)  # shrink toward "typical" when there is little data
            w[v] = round(min(2.0, max(0.5, math.exp(m))), 3)
        if w:
            out[a] = w
    return out


def build_learned(history, stats, now=None):
    rows = score_rows(history, stats, now)
    ranked = sorted(rows, key=lambda r: r["views"], reverse=True)
    pick = lambda r: {"title": r.get("title", ""), "views": r["views"], "mode": r.get("mode", ""), "hook": r.get("hook", "")}
    return {
        "updated": date.today().isoformat(),
        "videos_measured": len(rows),
        "typical_views": statistics.median(r["views"] for r in rows) if rows else 0,
        "weights": weights_from(rows),
        "best": [pick(r) for r in ranked[:6]],
        "worst": [pick(r) for r in ranked[-6:][::-1]] if len(ranked) >= 12 else [],
    }


def main():
    if not os.getenv("YT_API_KEY"):
        sys.exit("YT_API_KEY is missing (see the instructions): nothing to learn from yet")
    history = json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    uploads = fetch_uploads()
    print(f"channel has {len(uploads)} uploads; {len(history)} history entries")
    print(f"matched {attach_ids(history, uploads)} older entries to their video ids")
    ids = [h["video_id"] for h in history if h.get("video_id")]
    stats = fetch_stats(ids)
    print(f"stats for {len(stats)} videos")
    HISTORY.write_text(json.dumps(history, indent=2, ensure_ascii=False))
    learned = build_learned(history, stats)
    LEARNED.write_text(json.dumps(learned, indent=2, ensure_ascii=False))
    snap = json.loads(STATS.read_text()) if STATS.exists() else []  # views over time, for later analysis
    snap.append({"date": date.today().isoformat(), "views": {k: v["views"] for k, v in stats.items()}})
    STATS.write_text(json.dumps(snap[-60:], ensure_ascii=False))
    print(json.dumps({k: learned[k] for k in ("videos_measured", "typical_views", "weights")}, indent=2))


if __name__ == "__main__":
    main()
