"""Interactive CLI for Google Classroom backup.

Flow: auth -> select course(s) -> select resource types -> download
(with skip/resume/parallel) -> generate website.
"""
from __future__ import annotations

import logging
import sys

import questionary

from . import auth
from . import classroom_backup as cb
from . import log_setup
from . import main as backend
from . import build_site

log = logging.getLogger("classroom_cli")


def run() -> int:
    log_setup.setup_run_logging()

    print("=" * 60)
    print("  Google Classroom Backup")
    print("=" * 60)

    # 1. Auth
    if auth.TOKEN_PATH.exists():
        print(f"[auth] Reusing token at {auth.TOKEN_PATH}")
    else:
        print("[auth] No token found. Starting OAuth consent flow.")
        print("       A browser URL will be printed; complete consent in your browser.")
    try:
        creds = auth.load_credentials()
    except Exception as e:  # noqa: BLE001
        print(f"[auth] FAILED: {e}")
        return 1
    print(f"[auth] Authenticated as scopes={len(creds.scopes)}")

    classroom, drive, token = backend._services()

    # 2. Course selection
    print("[courses] Fetching course list...")
    courses = cb.list_courses(classroom)
    if not courses:
        print("No courses found.")
        return 0

    choices = [
        questionary.Choice(
            title=f"{c.get('name', c['id'])}  [{c.get('courseState', '')}]",
            value=c["id"],
        )
        for c in courses
    ]
    choices.append(questionary.Choice(title="== ALL courses ==", value="__all__"))

    selected = questionary.checkbox(
        "Select course(s) to back up (space to mark, enter to confirm):",
        choices=choices,
    ).ask()
    if selected is None:
        print("Cancelled.")
        return 0

    do_all = "__all__" in selected
    target_ids = [c["id"] for c in courses] if do_all else [s for s in selected if s != "__all__"]
    if not target_ids:
        print("No courses selected.")
        return 0

    # 3. Resource selection
    res = questionary.checkbox(
        "Select resource types to download:",
        choices=[
            questionary.Choice(title="Videos (Drive + YouTube)", value="videos", checked=True),
            questionary.Choice(title="Subtitles / transcripts", value="subtitles", checked=True),
            questionary.Choice(title="PDFs & Google Docs (exported)", value="pdfs", checked=True),
            questionary.Choice(title="Other files (images, sql, ipynb...)", value="other", checked=True),
        ],
    ).ask()
    if res is None:
        print("Cancelled.")
        return 0
    want = {
        "videos": "videos" in res,
        "subtitles": "subtitles" in res,
        "pdfs": "pdfs" in res,
        "other": "other" in res,
    }

    conns = questionary.text(
        "Parallel connections per video:",
        default="4",
        validate=lambda v: v.isdigit() and 1 <= int(v) <= 32,
    ).ask()
    connections = int(conns or 4)

    print(f"\n[plan] courses={len(target_ids)} want={want} connections={connections}")
    print("       topics/announcements/coursework/materials metadata: ALWAYS")
    print("       website: ALWAYS generated at the end\n")

    # 4. Download
    for cid in target_ids:
        try:
            backend.backup_course(
                classroom, drive, token, cid,
                download_drive=True, dry_run=False,
                want=want, connections=connections,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("Course %s failed: %s", cid, e)

    # 5. Website
    print("\n[site] Generating website...")
    out = build_site.build_site()
    print(f"[site] Written to {out}")
    print(f"[site] Serve with:  .venv/bin/python -m http.server 8000")
    print(f"[site] Then open:    http://localhost:8000/site/")
    return 0


if __name__ == "__main__":
    sys.exit(run())
