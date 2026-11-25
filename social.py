"""Posts the finished video as a Reel to your Facebook Page and your Instagram account, with Meta's official API.
Nothing here can stop a video from being made or uploaded: every problem is only printed.

Secrets (all optional; whatever is missing is skipped):
  FB_PAGE_ID, FB_PAGE_TOKEN   Facebook Page id and a Page access token
  IG_USER_ID                  Instagram Business account id (uses the same Page token by default)
  IG_TOKEN                    only if Instagram needs a different token than the Page token
"""
import os
import time
from pathlib import Path

import requests

GRAPH = os.getenv("META_GRAPH", "https://graph.facebook.com")
IG_GRAPH = os.getenv("IG_GRAPH", GRAPH)


def _check(r, what):
    try:
        d = r.json()
    except Exception:
        d = {"raw": r.text[:200]}
    if r.status_code >= 400 or (isinstance(d, dict) and d.get("error")):
        err = d.get("error", d) if isinstance(d, dict) else d
        raise RuntimeError(f"{what} failed: {err}")
    return d


def _push(upload_url, token, path):
    size = Path(path).stat().st_size
    with open(path, "rb") as f:
        r = requests.post(upload_url, headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)}, data=f, timeout=600)
    _check(r, "video upload")


def facebook_reel(path, caption):
    page, token = os.environ["FB_PAGE_ID"], os.environ["FB_PAGE_TOKEN"]
    d = _check(requests.post(f"{GRAPH}/{page}/video_reels", data={"upload_phase": "start", "access_token": token}, timeout=60), "facebook start")
    vid, url = d["video_id"], d["upload_url"]
    _push(url, token, path)
    _check(requests.post(f"{GRAPH}/{page}/video_reels", data={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED", "description": caption, "access_token": token}, timeout=120), "facebook publish")
    return vid


def instagram_reel(path, caption):
    ig, token = os.environ["IG_USER_ID"], os.getenv("IG_TOKEN") or os.environ["FB_PAGE_TOKEN"]
    d = _check(requests.post(f"{IG_GRAPH}/{ig}/media", data={"media_type": "REELS", "upload_type": "resumable", "caption": caption, "share_to_feed": "true", "access_token": token}, timeout=60), "instagram create")
    cid, url = d["id"], d["uri"]
    _push(url, token, path)
    status = ""
    for _ in range(40):  # Instagram processes the video for a while
        s = _check(requests.get(f"{IG_GRAPH}/{cid}", params={"fields": "status_code,status", "access_token": token}, timeout=60), "instagram status")
        status = s.get("status_code", "")
        if status in ("FINISHED", "ERROR", "EXPIRED"):
            break
        time.sleep(6)
    if status != "FINISHED":
        raise RuntimeError(f"instagram processing ended as {status or 'unknown'}")
    p = _check(requests.post(f"{IG_GRAPH}/{ig}/media_publish", data={"creation_id": cid, "access_token": token}, timeout=60), "instagram publish")
    return p.get("id")


def post_everywhere(path, caption, log=print):
    done = {}
    if os.getenv("FB_PAGE_ID") and os.getenv("FB_PAGE_TOKEN"):
        try:
            done["facebook"] = facebook_reel(path, caption)
            log(f"facebook reel posted ({done['facebook']})")
        except Exception as e:
            log(f"facebook: {str(e)[:300]}")
    else:
        log("facebook: secrets not set, skipping")
    if os.getenv("IG_USER_ID") and (os.getenv("IG_TOKEN") or os.getenv("FB_PAGE_TOKEN")):
        try:
            done["instagram"] = instagram_reel(path, caption)
            log(f"instagram reel posted ({done['instagram']})")
        except Exception as e:
            log(f"instagram: {str(e)[:300]}")
    else:
        log("instagram: secrets not set, skipping")
    return done
