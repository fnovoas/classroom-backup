"""Download YouTube videos referenced as Classroom attachments via yt-dlp."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

YTDLP = shutil.which("yt-dlp")


def download_video(video_id: str, dest_dir: Path, title: str = "") -> dict:
    """Download one YouTube video by id into dest_dir. Returns metadata."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://www.youtube.com/watch?v={video_id}"
    safe = "".join("_" if c in '<>:"/\\|?*\n\r\t' else c for c in (title or video_id)).strip() or video_id
    out_tmpl = str(dest_dir / f"{safe}.%(ext)s")

    if YTDLP:
        cmd = [YTDLP, "-f", "best", "-o", out_tmpl, "--no-playlist", "-q",
               "--concurrent-fragments", "4", "--retries", "5", "--fragment-retries", "5",
               url]
    else:
        cmd = ["yt-dlp", "-f", "best", "-o", out_tmpl, "--no-playlist", "-q",
               "--concurrent-fragments", "4", "--retries", "5", "--fragment-retries", "5",
               url]

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
    except FileNotFoundError:
        return {"id": video_id, "title": title, "error": "yt-dlp not installed"}
    except subprocess.CalledProcessError as e:
        return {
            "id": video_id,
            "title": title,
            "error": (e.stderr or b"").decode("utf-8", "replace")[:500],
        }
    except subprocess.TimeoutExpired:
        return {"id": video_id, "title": title, "error": "timeout"}

    for p in dest_dir.glob(f"{safe}.*"):
        return {"id": video_id, "title": title, "path": str(p), "url": url}
    return {"id": video_id, "title": title, "url": url, "error": "file not found after download"}
