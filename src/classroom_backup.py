"""Walk the Classroom API for a course and return plain dicts.

We deliberately keep this module side-effect free (no disk writes) so it can
be inspected in a dry run. main.py is responsible for persisting results.
"""
from __future__ import annotations

import socket
import time
from typing import Any, Iterable

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError

_RETRYABLE = (TimeoutError, socket.timeout, OSError)
_HTTP_RETRY_STATUSES = {429, 500, 502, 503, 504}


def _execute_with_retry(request, *, attempts: int = 5, base_delay: float = 5.0) -> Any:
    """Execute a Google API request with retries on transient failures."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return request.execute()
        except HttpError as e:
            if e.resp.status in _HTTP_RETRY_STATUSES:
                last = e
            else:
                raise
        except _RETRYABLE as e:
            last = e
        if attempt == attempts - 1:
            if last is not None:
                raise last
            raise RuntimeError("request failed without exception")
        time.sleep(base_delay * (2 ** attempt))
    raise RuntimeError("unreachable")


def _paginate(request_factory, list_key: str) -> Iterable[dict]:
    request = request_factory()
    while request is not None:
        response = _execute_with_retry(request)
        yield from response.get(list_key, [])
        token = response.get("nextPageToken")
        if not token:
            break
        request = request_factory(pageToken=token)


def list_courses(svc: Resource, states: list[str] | None = None) -> list[dict]:
    states = states or ["ACTIVE", "ARCHIVED"]
    return list(
        _paginate(
            lambda **kw: svc.courses().list(courseStates=states, pageSize=100, **kw),
            "courses",
        )
    )


def get_course(svc: Resource, course_id: str) -> dict:
    return _execute_with_retry(svc.courses().get(id=course_id))


def list_topics(svc: Resource, course_id: str) -> list[dict]:
    return list(
        _paginate(
            lambda **kw: svc.courses().topics().list(courseId=course_id, pageSize=100, **kw),
            "topic",
        )
    )


def list_announcements(svc: Resource, course_id: str) -> list[dict]:
    return list(
        _paginate(
            lambda **kw: svc.courses().announcements().list(courseId=course_id, pageSize=100, **kw),
            "announcements",
        )
    )


def list_coursework(svc: Resource, course_id: str) -> list[dict]:
    return list(
        _paginate(
            lambda **kw: svc.courses().courseWork().list(courseId=course_id, pageSize=100, **kw),
            "courseWork",
        )
    )


def list_coursework_materials(svc: Resource, course_id: str) -> list[dict]:
    return list(
        _paginate(
            lambda **kw: svc.courses().courseWorkMaterials().list(courseId=course_id, pageSize=100, **kw),
            "courseWorkMaterial",
        )
    )


def collect_attachments(obj: Any) -> dict:
    """Recursively collect every attachment in a Classroom object, categorized.

    Returns {'drive_files': [...], 'youtube': [...], 'links': [...],
    'forms': [...]}. Drive files de-duplicated by id.
    """
    out: dict = {
        "drive_files": {},
        "youtube": {},
        "links": {},
        "forms": {},
    }

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "driveFile" in node and isinstance(node["driveFile"], dict):
                df = node["driveFile"]
                fid = df.get("id")
                if fid and fid not in out["drive_files"]:
                    out["drive_files"][fid] = {
                        "id": fid,
                        "title": df.get("title", fid),
                        "alternateLink": df.get("alternateLink", ""),
                    }
            if "youtubeVideo" in node and isinstance(node["youtubeVideo"], dict):
                yv = node["youtubeVideo"]
                yid = yv.get("id")
                if yid and yid not in out["youtube"]:
                    out["youtube"][yid] = {
                        "id": yid,
                        "title": yv.get("title", yid),
                        "alternateLink": yv.get("alternateLink", ""),
                        "thumbnailUrl": yv.get("thumbnailUrl", ""),
                    }
            if "link" in node and isinstance(node["link"], dict):
                lk = node["link"]
                url = lk.get("url")
                if url and url not in out["links"]:
                    out["links"][url] = {
                        "url": url,
                        "title": lk.get("title", url),
                        "thumbnailUrl": lk.get("thumbnailUrl", ""),
                    }
            if "form" in node and isinstance(node["form"], dict):
                fm = node["form"]
                furl = fm.get("formUrl")
                if furl and furl not in out["forms"]:
                    out["forms"][furl] = {
                        "formUrl": furl,
                        "responseUrl": fm.get("responseUrl", ""),
                        "title": fm.get("title", "Form"),
                        "thumbnailUrl": fm.get("thumbnailUrl", ""),
                    }
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(obj)
    out["drive_files"] = list(out["drive_files"].values())
    out["youtube"] = list(out["youtube"].values())
    out["links"] = list(out["links"].values())
    out["forms"] = list(out["forms"].values())
    return out


def collect_drive_file_ids(obj: Any) -> list[dict]:
    """Backward-compatible wrapper returning only drive file ids."""
    return collect_attachments(obj)["drive_files"]
