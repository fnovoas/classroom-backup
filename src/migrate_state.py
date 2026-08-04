"""One-off migration: adopt existing downloads into download_state.json.

Renames extensionless video files to .mp4 and builds download_state.json from
materials_index.json so the new skip logic recognizes already-downloaded files.
"""
from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "site" / "backups"


def migrate_course(d: Path) -> None:
    idx_path = d / "materials_index.json"
    state_path = d / "download_state.json"
    mats = d / "materials"
    if not idx_path.exists():
        return
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    state: dict = {}
    adopted = 0
    for m in idx:
        fid = m.get("id")
        if not fid:
            continue
        old_name = Path(m.get("path", "")).name
        sz = m.get("size")
        via = m.get("downloadedVia", "get_media")
        if not old_name:
            continue
        # rename extensionless to .mp4
        target_name = old_name
        if "." not in old_name:
            target_name = old_name + ".mp4"
            old_p = mats / old_name
            new_p = mats / target_name
            if old_p.exists() and not new_p.exists():
                old_p.rename(new_p)
                print(f"  renamed {old_name} -> {target_name}")
        p = mats / target_name
        if p.exists() and sz is not None and p.stat().st_size == int(sz):
            state[fid] = {
                "complete": True,
                "size": sz,
                "filename": target_name,
                "via": via,
                "transcripts": m.get("transcripts", []),
            }
            adopted += 1
        elif p.exists() and sz is not None and p.stat().st_size != sz:
            print(f"  SIZE MISMATCH {target_name}: disk={p.stat().st_size} idx={sz} (will re-download)")
    # clean orphaned .part without sidecar
    for part in mats.glob("*.part"):
        if not part.with_suffix(".part.json").exists():
            part.unlink()
            print(f"  deleted orphan {part.name}")
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{d.name}: adopted {adopted}/{len(idx)} files into download_state.json")


def main() -> None:
    if not BASE.exists():
        print("no backups dir")
        return
    for d in sorted(BASE.iterdir()):
        if d.is_dir():
            print(f"=== {d.name} ===")
            migrate_course(d)


if __name__ == "__main__":
    main()
