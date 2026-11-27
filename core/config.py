"""설정과 비밀값

- 개인 데이터 위치: 환경변수 RICHCOACH_HOME, 없으면 ~/.richcoach
  (저장소 폴더 밖에 두어 git 에 섞이지 않게 함)
- 비밀값 우선순위: 환경변수 → ~/.richcoach/secrets.toml → .streamlit/secrets.toml
"""

import os
import tomllib
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent


def home() -> Path:
    p = Path(os.environ.get("RICHCOACH_HOME", Path.home() / ".richcoach")).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return home() / "richcoach.db"


def _toml(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return {}


def secret(name: str, default: str = "") -> str:
    if os.environ.get(name):
        return os.environ[name]
    for p in (home() / "secrets.toml", REPO_DIR / ".streamlit" / "secrets.toml"):
        v = _toml(p).get(name)
        if v:
            return str(v)
    return default
