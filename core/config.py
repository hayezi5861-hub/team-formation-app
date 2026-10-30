"""설정 읽기 모듈.

API 키·DB 주소·관리자 비밀번호는 코드에 쓰지 않고 아래 두 곳에서만 읽습니다.
  1) 환경 변수 (내 컴퓨터에서 실행할 때)
  2) Streamlit Secrets (.streamlit/secrets.toml 또는 Streamlit Cloud의 Secrets 창)
"""
from __future__ import annotations

import os

import streamlit as st

ADMIN_ID = "admin"
REQUIRED_SECRETS = ["SUPABASE_URL", "SUPABASE_KEY", "ADMIN_PASSWORD"]


def get_secret(name: str, default=None):
    value = os.environ.get(name)
    if value:
        return value
    try:
        return st.secrets[name]
    except Exception:  # secrets 파일이 없거나 항목이 없는 경우
        return default


def missing_required() -> list:
    return [name for name in REQUIRED_SECRETS if not get_secret(name)]


def openrouter_api_key():
    return get_secret("OPENROUTER_API_KEY")


def openrouter_models() -> list:
    """OPENROUTER_MODELS 에 적은 모델 이름을 순서대로 최대 3개 돌려줍니다.
    쉼표로 구분한 문자열 또는 TOML 배열 모두 가능합니다."""
    raw = get_secret("OPENROUTER_MODELS", "")
    if isinstance(raw, str):
        models = [m.strip() for m in raw.split(",")]
    else:
        models = [str(m).strip() for m in raw]
    return [m for m in models if m][:3]
