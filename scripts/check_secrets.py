"""커밋/푸시 전에 API 키, DB 주소, 비밀번호가 코드에 들어 있지 않은지 검사하는 스크립트.

사용법 (프로젝트 폴더에서):
    python scripts/check_secrets.py            # 프로젝트 전체 검사
    python scripts/check_secrets.py --staged   # git 에 올릴(staged) 파일만 검사
문제가 발견되면 목록을 보여 주고 종료 코드 1 로 끝납니다. (git 훅에 연결하면 커밋이 막힙니다)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (이름, 정규식) - 실제 비밀처럼 보이는 문자열 모양
PATTERNS = [
    ("OpenRouter API 키", re.compile(r"sk-or-[A-Za-z0-9_-]{16,}")),
    ("OpenAI/기타 sk- 키", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("JWT(Supabase anon/service_role 키 형태)", re.compile(r"eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}")),
    ("Supabase 새 secret 키", re.compile(r"\bsb_(?:secret|publishable)_[A-Za-z0-9_-]{10,}")),
    ("Supabase 프로젝트 주소", re.compile(r"https://[a-z0-9]{15,}\.supabase\.co")),
    ("DB 접속 문자열", re.compile(r"postgres(?:ql)?://[^\s:@]+:[^\s@]+@")),
    ("비밀 값 직접 대입",
     re.compile(r"""(?P<k>SUPABASE_URL|SUPABASE_KEY|OPENROUTER_API_KEY|ADMIN_PASSWORD)\s*=\s*["'](?P<v>[^"']+)["']""")),
]
# 예시 파일의 자리표시자(진짜 값이 아님)는 허용
PLACEHOLDER = re.compile(r"여기에|your[_-]|example|placeholder|xxxx|<.*>|test-not-a-real|test-admin-pw|example\.invalid", re.I)

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules"}
SKIP_NAMES = {"secrets.toml"}      # 진짜 비밀 파일은 .gitignore 로 제외되므로 내용 검사는 하지 않고 '추적 여부'만 봅니다
TEXT_SUFFIXES = {".py", ".md", ".toml", ".txt", ".sql", ".csv", ".json", ".yml", ".yaml", ".cfg", ".ini", ".env", ".example", ""}


def scan_text(text: str, label: str = "") -> list:
    """문자열 하나를 검사해 (이름, 줄 번호, 줄 내용 일부) 목록을 돌려줍니다."""
    findings = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, pattern in PATTERNS:
            m = pattern.search(line)
            if not m:
                continue
            value = m.groupdict().get("v") or m.group(0)
            if PLACEHOLDER.search(value) or PLACEHOLDER.search(line):
                continue
            findings.append((name, lineno, line.strip()[:80]))
    return findings


def iter_files(paths=None):
    if paths is not None:
        yield from (Path(p) for p in paths)
        return
    for path in ROOT.rglob("*"):
        if path.is_file() and not (set(path.relative_to(ROOT).parts) & SKIP_DIRS):
            yield path


def scan_paths(paths=None) -> list:
    results = []
    for path in iter_files(paths):
        path = path if path.is_absolute() else ROOT / path
        rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        if path.name in SKIP_NAMES or path.name == ".env" or path.suffix == ".env":
            results.append((str(rel), "비밀 파일은 GitHub 에 올리면 안 됩니다", 0, path.name))
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES or not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, lineno, snippet in scan_text(text):
            results.append((str(rel), name, lineno, snippet))
    return results


def staged_files() -> list:
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / line for line in out.splitlines() if line.strip()]


def main(argv) -> int:
    paths = staged_files() if "--staged" in argv else None
    results = scan_paths(paths)
    # 이미 git 이 추적 중인 secrets.toml 이 있는지도 확인
    try:
        tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
        for t in tracked:
            if Path(t).name in SKIP_NAMES or Path(t).suffix == ".env" or Path(t).name == ".env":
                results.append((t, "비밀 파일이 git 에 추적되고 있습니다", 0, t))
    except FileNotFoundError:
        pass
    if results:
        print("⚠️ 비밀 정보로 의심되는 내용이 있습니다:")
        for rel, name, lineno, snippet in results:
            where = f"{rel}:{lineno}" if lineno else rel
            print(f"  - {where}  [{name}]  {snippet}")
        print("\n코드에 직접 쓰지 말고 .streamlit/secrets.toml 이나 환경 변수로 옮기세요. "
              "이미 GitHub 에 올렸다면 해당 키를 즉시 폐기하고 새로 발급받으세요.")
        return 1
    print("✅ 비밀 정보로 의심되는 내용이 없습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
