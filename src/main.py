"""Backup orchestrator for Google Classroom courses.

Usage:
  python -m src.main --list
  python -m src.main --dry-run
  python -m src.main                       # all courses
  python -m src.main --course <id>
  python -m src.main --course <id> --no-drive
"""
from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
from pathlib import Path

from googleapiclient.errors import HttpError

from . import auth
from . import classroom_backup as cb
from . import drive_download as dd
from . import log_setup
from . import youtube_download as ytdl


def _safe(fn, label: str, log):
    try:
        return fn()
    except HttpError as e:
        log.warning("  %s failed: %s", label, e)
        return []
    except (TimeoutError, socket.timeout, OSError) as e:
        log.warning("  %s failed (timeout): %s", label, e)
        return []

log = logging.getLogger("classroom_backup")
BACKUPS = auth.BASE_DIR / "site" / "backups"


def _services():
    creds = auth.load_credentials()
    classroom = auth.build_service("classroom", "v1", creds)
    drive = auth.build_service("drive", "v3", creds)
    return classroom, drive, creds.token


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _slug(course: dict) -> str:
    name = course.get("name", course["id"]).strip()
    bad = '<>:"/\\|?*\n\r\t'
    safe = "".join("_" if c in bad else c for c in name)
    return f"{safe} [{course['id']}]"


def _course_folder(course_id: str) -> Path | None:
    matches = list(BACKUPS.glob(f"* [{course_id}]"))
    return matches[0] if matches else None


def _load_course(classroom, course_id: str) -> dict:
    try:
        return cb.get_course(classroom, course_id)
    except Exception as e:  # noqa: BLE001
        folder = _course_folder(course_id)
        cached = folder / "course.json" if folder else None
        if cached and cached.exists():
            log.warning("  get_course failed (%s); using cached course.json", e)
            return json.loads(cached.read_text(encoding="utf-8"))
        raise


def backup_course(
    classroom, drive, token: str, course_id: str, download_drive: bool, dry_run: bool,
    want: dict[str, bool] | None = None, connections: int = 8,
) -> None:
    if want is None:
        want = {"videos": True, "subtitles": True, "pdfs": True, "other": True}
    course = _load_course(classroom, course_id)
    folder = BACKUPS / _slug(course)
    log.info("Course: %s -> %s", course.get("name"), folder)

    topics = _safe(lambda: cb.list_topics(classroom, course_id), "topics", log)
    announcements = _safe(lambda: cb.list_announcements(classroom, course_id), "announcements", log)
    coursework = _safe(lambda: cb.list_coursework(classroom, course_id), "coursework", log)
    materials = _safe(lambda: cb.list_coursework_materials(classroom, course_id), "materials", log)

    log.info(
        "  topics=%d announcements=%d coursework=%d materials=%d",
        len(topics), len(announcements), len(coursework), len(materials),
    )

    if dry_run:
        return

    _write_json(folder / "course.json", course)
    _write_json(folder / "topics.json", topics)
    _write_json(folder / "announcements.json", announcements)
    _write_json(folder / "coursework.json", coursework)
    _write_json(folder / "coursework_materials.json", materials)

    if not download_drive:
        return

    file_log: dict = {}
    all_objs = [topics, announcements, coursework, materials]
    drive_files: dict[str, dict] = {}
    youtube_videos: dict[str, dict] = {}
    links: dict[str, dict] = {}
    forms: dict[str, dict] = {}
    for obj in all_objs:
        atts = cb.collect_attachments(obj)
        for f in atts["drive_files"]:
            drive_files[f["id"]] = f
        for y in atts["youtube"]:
            youtube_videos[y["id"]] = y
        for l in atts["links"]:
            links[l["url"]] = l
        for fm in atts["forms"]:
            forms[fm["formUrl"]] = fm

    log.info(
        "  attachments: drive=%d youtube=%d links=%d forms=%d",
        len(drive_files), len(youtube_videos), len(links), len(forms),
    )

    mats_dir = folder / "materials"
    mats_dir.mkdir(parents=True, exist_ok=True)

    # load download_state (authoritative completion marker)
    state_path = folder / "download_state.json"
    state: dict = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    already = dd.count_completed(state, drive_files)
    log.info("  %d already complete, %d to download", already, len(drive_files) - already)

    downloaded = []
    for fid, info in drive_files.items():
        log.info("    drive: %s", info.get("title", fid))
        meta = dd.download_file(drive, fid, mats_dir, file_log, token=token, want=want, connections=connections, state=state)
        if meta:
            downloaded.append(meta)
        # save state incrementally after each file
        _write_json(state_path, state)
    _write_json(folder / "materials_index.json", downloaded)

    if youtube_videos:
        vids_dir = mats_dir / "videos"
        vid_results = []
        for vid, info in youtube_videos.items():
            if state.get(f"yt_{vid}", {}).get("complete"):
                log.info("    youtube: %s (skipped)", info.get("title", vid))
                continue
            log.info("    youtube: %s", info.get("title", vid))
            res = ytdl.download_video(vid, vids_dir, info.get("title", ""))
            vid_results.append(res)
            if res.get("path"):
                state[f"yt_{vid}"] = {"complete": True, "filename": Path(res["path"]).name, "via": "ytdlp"}
                _write_json(state_path, state)
        _write_json(folder / "videos_index.json", vid_results)

    if links:
        _write_json(folder / "links.json", list(links.values()))
    if forms:
        _write_json(folder / "forms.json", list(forms.values()))

    _write_json(folder / "errors.json", file_log.get("errors", []))
    if file_log.get("errors"):
        log.warning("  %d file errors recorded", len(file_log["errors"]))


def _build_want(args) -> dict[str, bool]:
    any_flag = args.videos or args.subtitles or args.pdfs or args.other
    if not any_flag:
        return {"videos": True, "subtitles": True, "pdfs": True, "other": True}
    return {
        "videos": args.videos,
        "subtitles": args.subtitles,
        "pdfs": args.pdfs,
        "other": args.other,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Back up Google Classroom courses")
    p.add_argument("--list", action="store_true", help="List courses and exit")
    p.add_argument("--course", help="Back up a single course id")
    p.add_argument("--all", action="store_true", help="Back up all courses")
    p.add_argument("--dry-run", action="store_true", help="Walk APIs, write nothing")
    p.add_argument("--no-drive", action="store_true", help="Skip Drive file downloads")
    p.add_argument("--videos", action="store_true", help="Download videos")
    p.add_argument("--subtitles", action="store_true", help="Download subtitles")
    p.add_argument("--pdfs", action="store_true", help="Download PDFs/docs")
    p.add_argument("--other", action="store_true", help="Download other files")
    p.add_argument("--connections", type=int, default=8, help="Parallel connections per video")
    p.add_argument("--no-site", action="store_true", help="Skip website generation")
    args = p.parse_args(argv)

    log_setup.setup_run_logging()
    log.info("Logging to %s", log_setup.LOG_PATH)

    log.info("Loading Google credentials...")
    classroom, drive, token = _services()
    log.info("Connected to Google Classroom and Drive APIs")
    want = _build_want(args)

    if args.list:
        for c in cb.list_courses(classroom):
            print(f"{c['id']}\t{c.get('name','')}\t{c.get('courseState','')}")
        return 0

    if args.course:
        backup_course(classroom, drive, token, args.course, not args.no_drive, args.dry_run, want, args.connections)
        if not args.no_site:
            _gen_site()
        return 0

    courses = cb.list_courses(classroom)
    log.info("Found %d courses", len(courses))
    for c in courses:
        try:
            backup_course(classroom, drive, token, c["id"], not args.no_drive, args.dry_run, want, args.connections)
        except Exception as e:  # noqa: BLE001
            log.exception("Course %s failed: %s", c.get("name"), e)
    if not args.no_site:
        _gen_site()
    return 0


def _gen_site() -> None:
    try:
        from . import build_site
        out = build_site.build_site()
        log.info("Site written to %s", out)
    except Exception as e:  # noqa: BLE001
        log.warning("Site generation failed: %s", e)


if __name__ == "__main__":
    sys.exit(main())
