"""Download isolated audio from a YouTube URL via yt-dlp.

Only the audio track is kept (no video). Requires ``yt-dlp`` on PATH
(with the ``yt-dlp-ejs`` companion), ``ffmpeg``, and a supported JS
runtime (Deno preferred — shipped under ``youtube-downloader/bin/deno``).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Default container: widely supported and usually needs little/no re-encode.
DEFAULT_AUDIO_FORMAT = "m4a"
HERE = Path(__file__).resolve().parent
DEFAULT_QUEUE_FILE = HERE / "cola.txt"
# Long classroom lectures can exceed 3h; allow plenty of wall time.
DEFAULT_TIMEOUT_S = 6 * 3600
# Retries for a single queue item before aborting the whole queue.
DEFAULT_ITEM_RETRIES = 5
RETRY_SLEEP_S = 5


def _find_ytdlp() -> str | None:
    found = shutil.which("yt-dlp")
    if found:
        return found
    # Prefer the venv Scripts/bin next to this interpreter (do not resolve
    # symlinks — sys.executable often points at /usr/bin/python*).
    for base in (Path(sys.executable).parent, Path(sys.executable).resolve().parent):
        sibling = base / "yt-dlp"
        if sibling.exists():
            return str(sibling)
    return None


def _find_js_runtime() -> tuple[str, str] | None:
    """Return ``(runtime_name, absolute_path)`` for the first usable JS runtime.

    yt-dlp currently needs Deno (≥2.3) or Node (≥22) to solve YouTube JS
    challenges. Prefer the project-local Deno binary when present.
    """
    local_deno = HERE / "bin" / "deno"
    if local_deno.is_file() and os.access(local_deno, os.X_OK):
        return "deno", str(local_deno)

    for name in ("deno", "node", "nodejs"):
        path = shutil.which(name)
        if not path:
            continue
        # nodejs binary is still the "node" runtime for yt-dlp.
        runtime = "node" if name in {"node", "nodejs"} else name
        if runtime == "node":
            try:
                out = subprocess.run(
                    [path, "-v"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                major = int((out.stdout or "").lstrip("v").split(".", 1)[0])
            except (ValueError, subprocess.SubprocessError, OSError):
                continue
            if major < 22:
                continue
        return runtime, path
    return None


YTDLP = _find_ytdlp()


def _safe_name(text: str, fallback: str = "audio") -> str:
    cleaned = "".join("_" if c in '<>:"/\\|?*\n\r\t' else c for c in text).strip()
    return cleaned or fallback


def _video_id_from_url(url: str) -> str | None:
    """Best-effort extract of a YouTube video id from common URL shapes."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host in {"youtu.be", "www.youtu.be"}:
        vid = parsed.path.lstrip("/").split("/")[0]
        return vid or None
    if "youtube.com" in host or "youtube-nocookie.com" in host:
        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            return qs["v"][0]
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live", "v"}:
            return parts[1]
    m = re.search(r"(?:v=|/|youtu\.be/)([0-9A-Za-z_-]{11})", url)
    return m.group(1) if m else None


def _build_cmd(
    url: str,
    out_tmpl: str,
    *,
    audio_format: str,
    quiet: bool,
) -> list[str] | dict:
    ytdlp = YTDLP or "yt-dlp"
    js = _find_js_runtime()
    if not js:
        return {
            "error": (
                "No hay un runtime JS compatible para yt-dlp "
                "(Deno ≥2.3 o Node ≥22). Ejecuta: "
                "youtube-downloader/bin/install-deno.sh"
            ),
        }

    runtime, runtime_path = js
    cmd = [
        ytdlp,
        "--js-runtimes", f"{runtime}:{runtime_path}",
        "-f", "bestaudio/best",
        "-x",
        "--audio-format", audio_format,
        "--audio-quality", "0",
        "-o", out_tmpl,
        "--no-playlist",
        "--continue",
        "--retries", "10",
        "--fragment-retries", "10",
        "--retry-sleep", "http:linear=1:8:2",
        "--concurrent-fragments", "4",
    ]
    if quiet:
        cmd.append("-q")
    else:
        cmd.append("--progress")
    cmd.append(url)
    return cmd


def download_audio(
    url: str,
    dest_dir: Path,
    title: str = "",
    *,
    audio_format: str = DEFAULT_AUDIO_FORMAT,
    quiet: bool = False,
    timeout: int | None = DEFAULT_TIMEOUT_S,
) -> dict:
    """Download audio-only from a YouTube URL into ``dest_dir``.

    Returns a metadata dict with ``path`` on success, or ``error`` on failure.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    url = url.strip()
    video_id = _video_id_from_url(url) or "unknown"
    safe = _safe_name(title or video_id, fallback=video_id)
    out_tmpl = str(dest_dir / f"{safe}.%(ext)s")

    meta = {"id": video_id, "title": title, "url": url}
    built = _build_cmd(url, out_tmpl, audio_format=audio_format, quiet=quiet)
    if isinstance(built, dict):
        return {**meta, **built}
    cmd = built

    try:
        # Stream progress to the terminal for long lectures; only capture
        # stderr when quiet so callers can still inspect failures.
        if quiet:
            proc = subprocess.run(
                cmd, check=True, capture_output=True, timeout=timeout,
            )
            stderr = (proc.stderr or b"").decode("utf-8", "replace")
        else:
            proc = subprocess.run(cmd, check=True, timeout=timeout)
            stderr = ""
    except FileNotFoundError:
        return {**meta, "error": "yt-dlp not installed"}
    except subprocess.CalledProcessError as e:
        err = ""
        if quiet:
            err = (e.stderr or b"").decode("utf-8", "replace")
        elif e.stderr:
            err = e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, bytes) else str(e.stderr)
        return {**meta, "error": (err or f"yt-dlp exited with code {e.returncode}")[:800]}
    except subprocess.TimeoutExpired:
        return {**meta, "error": "timeout"}

    for p in dest_dir.glob(f"{safe}.*"):
        if p.suffix.lower() in {".part", ".ytdl", ".temp"}:
            continue
        return {**meta, "path": str(p), "format": p.suffix.lstrip(".")}
    # Prefer capturing any leftover diagnostic when quiet mode hid stderr.
    hint = stderr.strip()[:300] if stderr else "file not found after download"
    return {**meta, "error": hint}


def _prompt_url() -> str:
    print("=" * 60)
    print("  YouTube Audio Downloader")
    print("=" * 60)
    try:
        url = input("Pega la URL de YouTube y oprime Enter:\n> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelado.")
        raise SystemExit(1) from None
    if not url:
        print("No se ingresó una URL.")
        raise SystemExit(1)
    return url


def read_queue(queue_file: Path) -> list[str]:
    """Read URLs from ``cola.txt`` (one per line; ``#`` comments and blanks ignored)."""
    if not queue_file.is_file():
        return []
    urls: list[str] = []
    for raw in queue_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def write_queue(queue_file: Path, urls: list[str]) -> None:
    """Rewrite the queue file, preserving a simple one-URL-per-line format."""
    body = "\n".join(urls)
    if body:
        body += "\n"
    queue_file.write_text(body, encoding="utf-8")


def _existing_audio(dest_dir: Path, video_id: str) -> Path | None:
    """Return a finished audio file for ``video_id`` if one is already on disk."""
    for p in dest_dir.glob(f"{video_id}.*"):
        if p.suffix.lower() in {".part", ".ytdl", ".temp"}:
            continue
        if p.is_file() and p.stat().st_size > 0:
            return p
    return None


def download_with_retries(
    url: str,
    dest_dir: Path,
    *,
    audio_format: str = DEFAULT_AUDIO_FORMAT,
    max_retries: int = DEFAULT_ITEM_RETRIES,
) -> dict:
    """Download one URL, retrying the same item on failure before giving up."""
    last: dict = {}
    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            print(
                f"  Reintento {attempt}/{max_retries} en {RETRY_SLEEP_S}s "
                f"(no se pasa al siguiente hasta completar este)..."
            )
            try:
                time.sleep(RETRY_SLEEP_S)
            except KeyboardInterrupt:
                return {**last, "error": "cancelado", "cancelled": True}
        try:
            last = download_audio(
                url,
                dest_dir,
                audio_format=audio_format,
                quiet=False,
            )
        except KeyboardInterrupt:
            return {
                "url": url,
                "id": _video_id_from_url(url) or "unknown",
                "error": "cancelado",
                "cancelled": True,
            }
        if last.get("path"):
            return last
        print(f"  Falló: {last.get('error', 'unknown')}")
    return last


def run_queue(
    queue_file: Path,
    dest_dir: Path,
    *,
    audio_format: str = DEFAULT_AUDIO_FORMAT,
    max_retries: int = DEFAULT_ITEM_RETRIES,
) -> int:
    """Process ``cola.txt`` sequentially; only advance after a successful download.

    Completed URLs are removed from the file so an interrupted run resumes at
    the first pending item. Failures are retried on the same URL before moving on.
    """
    urls = read_queue(queue_file)
    if not urls:
        print(f"Cola vacía: {queue_file}")
        return 0

    total = len(urls)
    print("=" * 60)
    print("  YouTube Audio Downloader — cola")
    print("=" * 60)
    print(f"Archivo: {queue_file}")
    print(f"Pendientes: {total}")
    print(f"Destino: {dest_dir}")
    print()

    pending = list(urls)
    done = 0
    while pending:
        url = pending[0]
        idx = done + 1
        remaining = len(pending)
        video_id = _video_id_from_url(url) or "unknown"
        print("-" * 60)
        print(f"[{idx}/{done + remaining}] {url}")

        existing = _existing_audio(dest_dir, video_id)
        if existing:
            print(f"  Ya descargado: {existing} (se omite y se quita de la cola)")
            pending.pop(0)
            write_queue(queue_file, pending)
            done += 1
            continue

        result = download_with_retries(
            url,
            dest_dir,
            audio_format=audio_format,
            max_retries=max_retries,
        )
        if result.get("cancelled"):
            print("\nInterrumpido. La URL actual permanece en la cola.")
            write_queue(queue_file, pending)
            return 130
        if not result.get("path"):
            print(
                f"\nAbortando cola: no se pudo completar el ítem actual tras "
                f"{max_retries} intentos.\n"
                f"  URL: {url}\n"
                f"  Error: {result.get('error', 'unknown')}\n"
                f"Vuelve a ejecutar el comando para reintentar desde este punto."
            )
            write_queue(queue_file, pending)
            return 1

        print(f"  Listo: {result['path']}")
        pending.pop(0)
        write_queue(queue_file, pending)
        done += 1

    print()
    print(f"Cola terminada: {done} audio(s) descargado(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Download isolated audio from a YouTube URL or from cola.txt.",
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=None,
        help="YouTube video URL (si se omite, se pide en la terminal)",
    )
    parser.add_argument(
        "--cola", "--queue",
        nargs="?",
        const=str(DEFAULT_QUEUE_FILE),
        default=None,
        metavar="FILE",
        help=(
            "Procesar cola de URLs (por defecto: youtube-downloader/cola.txt). "
            "Descarga una por una; reintenta el ítem actual antes de seguir."
        ),
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=HERE / "downloads",
        help="Destination directory (default: youtube-downloader/downloads)",
    )
    parser.add_argument(
        "-t", "--title",
        default="",
        help="Optional filename stem (defaults to video id; ignored with --cola)",
    )
    parser.add_argument(
        "--format",
        default=DEFAULT_AUDIO_FORMAT,
        dest="audio_format",
        help=f"Audio container (default: {DEFAULT_AUDIO_FORMAT})",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_ITEM_RETRIES,
        help=f"Reintentos por ítem de la cola (default: {DEFAULT_ITEM_RETRIES})",
    )
    args = parser.parse_args(argv)

    js = _find_js_runtime()
    if not js:
        print(
            "Error: hace falta Deno (≥2.3) o Node (≥22) para YouTube.\n"
            "  Ejecuta:  bash youtube-downloader/bin/install-deno.sh",
            file=sys.stderr,
        )
        return 1
    print(f"Runtime JS: {js[0]} ({js[1]})")

    if args.cola is not None:
        queue_file = Path(args.cola).expanduser()
        if not queue_file.is_file():
            # Allow relative names resolved from the module directory.
            alt = HERE / queue_file.name
            if alt.is_file():
                queue_file = alt
        return run_queue(
            queue_file,
            args.output_dir,
            audio_format=args.audio_format,
            max_retries=max(1, args.retries),
        )

    url = args.url or _prompt_url()
    print(f"Descargando audio de: {url}")
    print("(videos largos pueden tardar varios minutos; se muestra el progreso)")
    result = download_audio(
        url,
        args.output_dir,
        title=args.title,
        audio_format=args.audio_format,
        quiet=False,
    )
    if result.get("path"):
        print(f"Listo: {result['path']}")
        return 0
    print(f"Error: {result.get('error', 'unknown')}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
