"""Stream view-only Drive videos and fetch their transcripts.

View-only Drive videos (canDownload=False) can't be fetched via the Drive API
`get_media` (403). They CAN be streamed through the same `get_video_info`
endpoint the Classroom/Drive web player uses. Downloads use parallel chunked
Range requests with retry/backoff, plus a .part + .part.json sidecar for resume.
"""
from __future__ import annotations

from . import auth  # noqa: F401 — apply IPv4 preference for urllib

import json
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

CHUNK = 1 << 20  # 1 MB sub-chunk per Range request
DEFAULT_CONNECTIONS = 4
MAX_RETRIES = 5
BACKOFF_403 = [10, 20, 40, 60, 60]
BACKOFF_OTHER = [2, 4, 8, 16, 32]


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def get_video_info(file_id: str, token: str) -> dict:
    url = f"https://drive.google.com/get_video_info?docid={file_id}&authuser=0"
    body = urllib.request.urlopen(
        urllib.request.Request(url, headers=_bearer(token)), timeout=30
    ).read().decode("utf-8", "replace")
    d = dict(urllib.parse.parse_qsl(body))
    if d.get("status") != "ok":
        raise RuntimeError(f"get_video_info status={d.get('status')}")
    return d


def pick_best_stream(info: dict) -> dict | None:
    raw = info.get("url_encoded_fmt_stream_map") or info.get("fmt_stream_map") or ""
    if not raw:
        return None

    candidates = []
    for s in raw.split(","):
        if not s:
            continue
        parsed = dict(urllib.parse.parse_qsl(s, keep_blank_values=True))
        if not parsed:
            continue
        itag = parsed.get("itag", "")
        wh = 0
        for entry in info.get("fmt_list", "").split(","):
            parts = entry.split("/")
            if parts and parts[0] == itag and len(parts) > 1 and "x" in parts[1]:
                w, h = parts[1].split("x", 1)
                wh = int(w) * int(h)
        parsed["_pixels"] = wh
        candidates.append(parsed)
    if not candidates:
        return None
    candidates.sort(key=lambda c: c["_pixels"], reverse=True)
    return candidates[0]


def _total_size(stream_url: str, token: str) -> int:
    req = urllib.request.Request(stream_url, headers={**_bearer(token), "Range": "bytes=0-0"})
    r = urllib.request.urlopen(req, timeout=30)
    cr = r.headers.get("Content-Range", "")
    return int(cr.split("/")[-1]) if "/" in cr else 0


def _commit_part_file(part: Path, target: Path) -> None:
    if target.exists():
        target.unlink()
    os.replace(part, target)


def _download_segment(
    stream_url: str, token: str, start: int, end: int, fh, lock, seg_idx: int
) -> int:
    """Download bytes [start, end] into fh at offset start, with retry/backoff."""
    written = 0
    cur = start
    while cur <= end:
        chunk_end = min(cur + CHUNK - 1, end)
        for attempt in range(MAX_RETRIES):
            try:
                req = urllib.request.Request(
                    stream_url,
                    headers={**_bearer(token), "Range": f"bytes={cur}-{chunk_end}"},
                )
                data = urllib.request.urlopen(req, timeout=120).read()
                if data:
                    break
            except Exception as ex:
                is_403 = getattr(ex, "code", None) == 403
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep((BACKOFF_403 if is_403 else BACKOFF_OTHER)[attempt])
        else:
            raise RuntimeError(f"segment {seg_idx}: no data after retries")
        with lock:
            fh.seek(cur)
            fh.write(data)
        written += len(data)
        cur += len(data)
    return written


def stream_video(
    file_id: str,
    token: str,
    target: Path,
    log: dict[str, Any],
    connections: int = DEFAULT_CONNECTIONS,
) -> dict | None:
    import threading

    part = target.with_suffix(target.suffix + ".part")
    sidecar = target.with_suffix(target.suffix + ".part.json")

    try:
        info = get_video_info(file_id, token)
    except Exception as e:
        log.setdefault("errors", []).append({"id": file_id, "phase": "get_video_info", "error": str(e)[:300]})
        return None

    stream = pick_best_stream(info)
    if not stream:
        log.setdefault("errors", []).append({"id": file_id, "phase": "streams", "error": "no stream map"})
        return None
    stream_url = stream["url"]

    try:
        total = _total_size(stream_url, token)
    except Exception as e:
        log.setdefault("errors", []).append({"id": file_id, "phase": "stream_head", "error": str(e)[:300]})
        return None
    if total <= 0:
        log.setdefault("errors", []).append({"id": file_id, "phase": "size", "error": f"total={total}"})
        return None

    seg_size = max(CHUNK, (total + connections - 1) // connections)
    n_segs = (total + seg_size - 1) // seg_size
    done_segs = [False] * n_segs

    if sidecar.exists():
        try:
            sc = json.loads(sidecar.read_text())
            if sc.get("total") == total and sc.get("itag") == stream.get("itag"):
                done_segs = sc.get("done_segs", [False] * n_segs)
                if len(done_segs) != n_segs:
                    done_segs = [False] * n_segs
        except Exception:
            pass

    lock = threading.Lock()

    def save_sidecar() -> None:
        sidecar.write_text(json.dumps({"total": total, "itag": stream.get("itag"), "done_segs": done_segs}))

    def run_segments(seg_indices: list[int], parallel: int) -> list[int]:
        """Download given segments. Returns list of segment indices that failed."""
        failed: list[int] = []
        if not seg_indices:
            return failed
        if parallel <= 1 or len(seg_indices) == 1:
            for i in seg_indices:
                s = i * seg_size
                e = min(s + seg_size - 1, total - 1)
                try:
                    _download_segment(stream_url, token, s, e, fh, lock, i)
                    done_segs[i] = True
                    save_sidecar()
                    pct = 100 * sum(done_segs) / n_segs
                    log.setdefault("progress", None)
                    print(f"      seg {i+1}/{n_segs} done ({pct:.0f}%)", flush=True)
                except Exception as ex:
                    failed.append(i)
                    log.setdefault("errors", []).append({"id": file_id, "phase": f"seg{i}", "error": str(ex)[:200]})
            return failed
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futs = {}
            for i in seg_indices:
                s = i * seg_size
                e = min(s + seg_size - 1, total - 1)
                futs[pool.submit(_download_segment, stream_url, token, s, e, fh, lock, i)] = i
            for fut in as_completed(futs):
                i = futs[fut]
                try:
                    fut.result()
                    done_segs[i] = True
                    save_sidecar()
                    pct = 100 * sum(done_segs) / n_segs
                    print(f"      seg {i+1}/{n_segs} done ({pct:.0f}%)", flush=True)
                except Exception as ex:
                    failed.append(i)
                    log.setdefault("errors", []).append({"id": file_id, "phase": f"seg{i}", "error": str(ex)[:200]})
        return failed

    try:
        with part.open("r+b" if part.exists() else "wb") as fh:
            fh.seek(0, 2)
            if fh.tell() < total:
                fh.seek(total - 1)
                fh.write(b"\x00")

            pending = [i for i in range(n_segs) if not done_segs[i]]
            print(f"    streaming {total/1048576:.1f} MB, {n_segs} segments, {len(pending)} pending, {connections} parallel", flush=True)
            failed = run_segments(pending, connections)
            if failed:
                print(f"    {len(failed)} segments failed parallel; pausing 20s then retrying sequentially", flush=True)
                time.sleep(20)
                failed = run_segments(failed, 1)
    except Exception as e:
        log.setdefault("errors", []).append({"id": file_id, "phase": "stream", "error": str(e)[:300]})
        return None

    if not all(done_segs):
        log.setdefault("errors", []).append({"id": file_id, "phase": "incomplete", "error": "segments missing after retry"})
        return None

    _commit_part_file(part, target)
    sidecar.unlink(missing_ok=True)
    return {
        "downloadedVia": "stream",
        "itag": stream.get("itag"),
        "quality": stream.get("quality"),
        "size": total,
        "filename": target.name,
    }


def fetch_transcripts(file_id: str, token: str, video_path: Path) -> list[dict]:
    results: list[dict] = []
    try:
        info = get_video_info(file_id, token)
    except Exception:
        return results

    ttsurl = urllib.parse.unquote(info.get("ttsurl", ""))
    if not ttsurl:
        return results

    try:
        list_xml = urllib.request.urlopen(ttsurl + "&type=list", timeout=20).read().decode("utf-8", "replace")
    except Exception:
        return results

    tracks = re.findall(
        r'<track\s+id="(\d+)"\s+kind="([^"]*)"\s+name="([^"]*)"\s+lang_code="([^"]*)"',
        list_xml,
    )
    if not tracks:
        return results

    base = video_path.with_suffix("")
    for tid, kind, name, lang in tracks:
        saved = False
        for fmt in ("vtt", "ttml"):
            try:
                url = f"{ttsurl}&type=track&id={tid}&kind={kind}&lang={lang}&fmt={fmt}"
                content = urllib.request.urlopen(url, timeout=60).read().decode("utf-8", "replace")
            except Exception:
                continue
            if fmt == "vtt":
                vtt_path = base.with_name(f"{base.name}.{lang}.vtt")
                vtt_path.write_text(content, encoding="utf-8")
                txt_path = base.with_name(f"{base.name}.{lang}.txt")
                txt_path.write_text(_vtt_to_plain(content), encoding="utf-8")
                results.append({"lang": lang, "kind": kind, "format": "vtt", "vtt": vtt_path.name, "txt": txt_path.name})
                saved = True
                break
        if not saved:
            try:
                url = f"{ttsurl}&type=track&id={tid}&kind={kind}&lang={lang}&fmt=ttml"
                content = urllib.request.urlopen(url, timeout=60).read().decode("utf-8", "replace")
                ttml_path = base.with_name(f"{base.name}.{lang}.ttml")
                ttml_path.write_text(content, encoding="utf-8")
                results.append({"lang": lang, "kind": kind, "format": "ttml", "ttml": ttml_path.name})
            except Exception:
                pass
    return results


def _vtt_to_plain(vtt: str) -> str:
    lines = []
    for block in vtt.split("\n\n"):
        block = block.strip()
        if not block or block.startswith("WEBVTT"):
            continue
        parts = block.split("\n", 1)
        if len(parts) < 2:
            continue
        cue = parts[0].strip()
        text = parts[1].strip().replace("\n", " ")
        text = re.sub(r"<[^>]+>", "", text)
        lines.append(f"[{cue}] {text}")
    return "\n".join(lines)
