"""비밀번호 해시 모듈.

'해시'란? 비밀번호를 되돌릴 수 없는 긴 문자열로 바꾸는 것입니다.
DB가 유출되어도 원래 비밀번호를 알 수 없도록, DB에는 해시만 저장합니다.
파이썬 기본 라이브러리(hashlib)만 사용하므로 별도 설치가 필요 없습니다.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

ITERATIONS = 100_000  # 계산을 일부러 느리게 만들어 무차별 대입 공격을 어렵게 함


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)  # 같은 비밀번호도 서로 다른 해시가 되도록 섞는 값
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def verify_admin_password(password: str, expected: str) -> bool:
    """관리자 비밀번호는 Secrets 에 있는 값과 비교합니다. (시간차 공격 방지용 비교 함수 사용)"""
    if not expected:
        return False
    return hmac.compare_digest(password.encode("utf-8"), str(expected).encode("utf-8"))
