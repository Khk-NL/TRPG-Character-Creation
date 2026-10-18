#!/usr/bin/env python3
"""Publish maintained DND skill code; never publish supplied workbooks or CHM files."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

REMOTE = "https://github.com/Khk-NL/TRPG-Character-Creation.git"
FILES = (
    "SKILL.md", "README.md", "agents/openai.yaml", "assets/intake-form.html",
    "references/rules.md", "references/plan-schema.md", "references/template-known-issues.md",
    "scripts/fill_character.py", "scripts/publish_skill.py",
)


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def publish(source: Path) -> str:
    missing = [name for name in FILES if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError("待发布文件缺失：" + "、".join(missing))
    with tempfile.TemporaryDirectory(prefix="dnd-skill-publish-") as temporary:
        checkout = Path(temporary) / "repo"
        git("clone", "--quiet", REMOTE, str(checkout), cwd=source)
        for name in FILES:
            target = checkout / "dnd-character" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, target)
        git("add", "--", *["dnd-character/" + name for name in FILES], cwd=checkout)
        changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=checkout)
        if changed.returncode == 0:
            return "远端已是最新"
        if changed.returncode != 1:
            raise RuntimeError("无法检查发布差异")
        git("commit", "-m", "Update DND 5E and 5R character skill", cwd=checkout)
        git("push", "origin", "HEAD", cwd=checkout)
        return git("rev-parse", "HEAD", cwd=checkout).stdout.strip()


if __name__ == "__main__":
    try:
        print(publish(Path(__file__).resolve().parents[1]))
    except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
        raise SystemExit(f"发布失败：{error}") from error
