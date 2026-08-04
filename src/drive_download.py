"""Download Drive files referenced by Classroom materials.

- Regular files (pdf, docx, images, ...): streamed via files.get_media.
- Google-native docs (Docs/Sheets/Slides/Drawings): exported to PDF.
- View-only videos (canDownload=False): streamed via get_video_info + parallel chunks.
- Completion tracked in download_state.json (filename + actual size), mount-independent.
- Idempotent: skipped when download_state marks complete and file size matches.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from . import drive_video

NATIVE_EXPORT_MIME = {
    "application/vnd.google-apps.document": "application/pdf",
    "application/vnd.google-apps.spreadsheet": "application/pdf",
    "application/vnd.google-apps.presentation": "application/pdf",
    "application/vnd.google-apps.drawing": "application/pdf",
}


def _safe_name(name: str) -> str:
    bad = '<>:"/\\|?*\n\r\t'
    return "".join("_" if c in bad else c for c in name).strip() or "unnamed"


def _load_state(dest_dir: Path) -> dict:
    p = dest_dir.parent / "download_state.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(dest_dir: Path, state: dict) -> None:
    p = dest_dir.parent / "download_state.json"
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _is_state_complete(st: dict, dest_dir: Path, target: Path) -> bool:
    """True when download_state marks a file done and the file is on disk."""
    if not st or not st.get("complete"):
        return False
    if st.get("skipped") and st.get("reason") == "view_only":
        return False
    fname = st.get("filename", "")
    sz = st.get("size")
    existing = dest_dir / fname if fname else target
    return bool(existing.exists() and sz is not None and existing.stat().st_size == int(sz))


def count_completed(state: dict, file_ids: Iterable[str]) -> int:
    """Count files marked complete in state, excluding failed view-only skips."""
    return sum(
        1
        for fid in file_ids
        if (st := state.get(fid))
        and st.get("complete")
        and not (st.get("skipped") and st.get("reason") == "view_only")
    )


def _download_block_reason(meta: dict[str, Any]) -> str | None:
    capabilities = meta.get("capabilities") or {}
    if isinstance(capabilities, dict) and capabilities.get("canDownload") is False:
        return "view_only"
    return None


def download_file(
    drive: Resource,
    file_id: str,
    dest_dir: Path,
    log: dict[str, Any],
    token: str = "",
    want: dict[str, bool] | None = None,
    connections: int = 4,
    state: dict | None = None,
) -> dict | None:
    """Download one file by id into dest_dir. Returns metadata dict or None."""
    if want is None:
        want = {"videos": True, "subtitles": True, "pdfs": True, "other": True}
    if state is None:
        state = {}

    import time as _time

    meta = None
    for _attempt in range(3):
        try:
            meta = (
                drive.files()
                .get(
                    fileId=file_id,
                    fields="id,name,mimeType,modifiedTime,size,md5Checksum,originalFilename,capabilities",
                )
                .execute()
            )
            break
        except HttpError as e:
            log.setdefault("errors", []).append({"id": file_id, "phase": "get", "error": str(e)})
            return None
        except Exception as e:
            if _attempt == 2:
                log.setdefault("errors", []).append({"id": file_id, "phase": "get", "error": f"timeout: {str(e)[:150]}"})
                return None
            _time.sleep(2 ** _attempt)
    if not meta:
        return None

    name = _safe_name(meta.get("name") or meta.get("originalFilename") or file_id)
    mime = meta.get("mimeType", "")
    is_video = mime.startswith("video/")
    is_pdf = mime == "application/pdf" or name.lower().endswith(".pdf")

    if is_video and not name.lower().endswith((".mp4", ".webm", ".mkv", ".mov", ".m4v")):
        name = name + ".mp4"
        if meta.get("originalFilename") and not name.count("."):
            pass

    target = dest_dir / name

    # resource-type gating
    if is_video and not want.get("videos"):
        meta["skipped"] = "videos_disabled"
        return meta
    if mime in NATIVE_EXPORT_MIME and not want.get("pdfs"):
        meta["skipped"] = "pdfs_disabled"
        return meta
    if not is_video and mime not in NATIVE_EXPORT_MIME and is_pdf and not want.get("pdfs"):
        meta["skipped"] = "pdfs_disabled"
        return meta
    if not is_video and mime not in NATIVE_EXPORT_MIME and not is_pdf and not want.get("other"):
        meta["skipped"] = "other_disabled"
        return meta

    # ---- authoritative skip via download_state ----
    st = state.get(file_id)
    if _is_state_complete(st, dest_dir, target):
        existing = dest_dir / st.get("filename", target.name)
        meta["path"] = str(existing)
        meta["filename"] = existing.name
        meta["skipped"] = True
        meta["size"] = st.get("size")
        if want.get("subtitles") and token and is_video:
            _attach_transcripts(file_id, token, existing, meta, log)
        return meta

    blocked_reason = _download_block_reason(meta)
    if blocked_reason == "view_only":
        if is_video and token:
            print(f"    view-only video, streaming: {name}", flush=True)
            sres = drive_video.stream_video(file_id, token, target, log, connections=connections)
            if sres:
                meta.update(sres)
                meta["path"] = str(target)
                meta["filename"] = target.name
                _mark_complete(state, file_id, target, "stream", dest_dir, meta)
                if want.get("subtitles") and meta.get("path"):
                    _attach_transcripts(file_id, token, target, meta, log)
                    _mark_complete(state, file_id, target, "stream", dest_dir, meta)
                return meta
            log.setdefault("errors", []).append(
                {"id": file_id, "phase": "stream", "error": "view-only stream failed"}
            )
            return None
        print(f"    skipping view-only Drive file: {name}", flush=True)
        meta["skipped"] = blocked_reason
        meta["downloadError"] = "Drive file is view-only and cannot be downloaded with the current account"
        meta["filename"] = target.name
        meta["path"] = str(target)
        _mark_skipped(state, file_id, target, "skipped", meta, blocked_reason)
        return meta

    if mime in NATIVE_EXPORT_MIME:
        export_mime = NATIVE_EXPORT_MIME[mime]
        target = target.with_suffix(".pdf")
        try:
            resp = drive.files().export(fileId=file_id, mimeType=export_mime).execute()
            target.write_bytes(resp if isinstance(resp, bytes) else _to_bytes(resp))
            meta["exportedAs"] = export_mime
            meta["path"] = str(target)
            meta["filename"] = target.name
            meta["size"] = target.stat().st_size
            _mark_complete(state, file_id, target, "export", dest_dir, meta)
            return meta
        except HttpError as e:
            log.setdefault("errors", []).append({"id": file_id, "phase": "export", "error": str(e)})
            return None

    # md5 skip for non-video binary files with a checksum
    md5 = meta.get("md5Checksum")
    if not is_video and target.exists() and md5:
        from hashlib import md5 as _md5

        h = _md5()
        with target.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() == md5:
            meta["path"] = str(target)
            meta["filename"] = target.name
            meta["skipped"] = True
            _mark_complete(state, file_id, target, "get_media", dest_dir, meta)
            return meta

    # discard stale partial without sidecar
    part = target.with_suffix(target.suffix + ".part")
    sidecar = target.with_suffix(target.suffix + ".part.json")
    if part.exists() and not sidecar.exists():
        part.unlink(missing_ok=True)
    if part.exists() and sidecar.exists() and target.exists():
        part.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)

    try:
        request = drive.files().get_media(fileId=file_id)
        with target.open("wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=1 << 20)
            done = False
            while not done:
                _status, done = downloader.next_chunk()
        meta["path"] = str(target)
        meta["filename"] = target.name
        meta["downloadedVia"] = "get_media"
        meta["size"] = target.stat().st_size
        _mark_complete(state, file_id, target, "get_media", dest_dir, meta)
    except HttpError as e:
        if is_video and token:
            print(f"    get_media 403, trying stream: {name}", flush=True)
            sres = drive_video.stream_video(file_id, token, target, log, connections=connections)
            if sres:
                meta.update(sres)
                meta["path"] = str(target)
                meta["filename"] = target.name
                _mark_complete(state, file_id, target, "stream", dest_dir, meta)
            else:
                log.setdefault("errors", []).append({"id": file_id, "phase": "download", "error": str(e)[:300]})
                if target.exists():
                    target.unlink(missing_ok=True)
                return None
        else:
            log.setdefault("errors", []).append({"id": file_id, "phase": "download", "error": str(e)})
            if target.exists():
                target.unlink(missing_ok=True)
            return None

    if is_video and token and meta.get("path") and want.get("subtitles"):
        _attach_transcripts(file_id, token, Path(meta["path"]), meta, log)
        if meta.get("transcripts"):
            _mark_complete(state, file_id, target, meta.get("downloadedVia", "get_media"), dest_dir, meta)

    return meta


def _mark_complete(state: dict, file_id: str, target: Path, via: str, dest_dir: Path, meta: dict) -> None:
    state[file_id] = {
        "complete": True,
        "size": target.stat().st_size if target.exists() else meta.get("size"),
        "filename": target.name,
        "via": via,
        "transcripts": meta.get("transcripts", []),
    }


def _mark_skipped(state: dict, file_id: str, target: Path, via: str, meta: dict, reason: str) -> None:
    state[file_id] = {
        "complete": True,
        "skipped": True,
        "reason": reason,
        "size": target.stat().st_size if target.exists() else meta.get("size"),
        "filename": target.name,
        "via": via,
        "transcripts": meta.get("transcripts", []),
    }


def _attach_transcripts(file_id: str, token: str, target: Path, meta: dict, log: dict) -> None:
    try:
        trs = drive_video.fetch_transcripts(file_id, token, target)
        if trs:
            meta["transcripts"] = trs
    except Exception as e:
        log.setdefault("errors", []).append({"id": file_id, "phase": "transcript", "error": str(e)[:300]})


def _to_bytes(resp: Any) -> bytes:
    if isinstance(resp, bytes):
        return resp
    if isinstance(resp, str):
        return resp.encode("utf-8")
    return json.dumps(resp).encode("utf-8")
