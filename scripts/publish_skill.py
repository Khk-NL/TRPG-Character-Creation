#!/usr/bin/env python3
"""Publish only the installed skill's maintained files to its GitHub repository."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


REMOTE = "https://github.com/Khk-NL/TRPG-Character-Creation.git"
FILES = (
    "SKILL.md",
    ".gitignore",
    "agents/openai.yaml",
    "assets/COC七版规则空白卡20.6.1.xlsx",
    "assets/intake-form.html",
    "references/background-writing.md",
    "references/build-decisions.md",
    "references/code-references.md",
    "references/input-schema.md",
    "references/publishing.md",
    "references/rules.md",
    "references/workbook-map.md",
    "scripts/fill_investigator.py",
    "scripts/publish_skill.py",
    "tests/sample-plan.json",
    "tests/test_fill_investigator.py",
)


def git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=check, text=True, capture_output=True)


def publish(source: Path, remote: str = REMOTE) -> str:
    source = source.resolve(strict=True)
    missing = [relative for relative in FILES if not (source / relative).is_file()]
    if missing:
        raise FileNotFoundError("发布文件缺失：" + "、".join(missing))
    with tempfile.TemporaryDirectory(prefix="coc7-publish-") as temp:
        checkout = Path(temp) / "repo"
        git("clone", "--quiet", remote, str(checkout))
        for relative in FILES:
            destination = checkout / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, destination)
        git("add", "--", *FILES, cwd=checkout)
        staged = git("diff", "--cached", "--quiet", cwd=checkout, check=False)
        if staged.returncode == 0:
            return "远端已是最新，无需推送"
        if staged.returncode != 1:
            raise RuntimeError(staged.stderr.strip() or "无法检查待发布变更")
        git("commit", "-m", "Update COC7 investigator skill", cwd=checkout)
        git("push", "origin", "HEAD", cwd=checkout)
        return git("rev-parse", "HEAD", cwd=checkout).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Commit and push maintained COC7 skill files")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--remote", default=REMOTE)
    args = parser.parse_args()
    try:
        print(publish(args.source, args.remote))
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            message = (exc.stderr or exc.stdout or str(exc)).strip()
        else:
            message = str(exc)
        raise SystemExit(f"发布失败：{message}") from exc


if __name__ == "__main__":
    main()
