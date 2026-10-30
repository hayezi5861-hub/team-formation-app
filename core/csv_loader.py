"""CSV 파일 읽기 모듈.

- 열: student_no, name, main_role, sub_roles
- UTF-8 BOM(엑셀이 붙이는 보이지 않는 표시)과 한글을 지원합니다.
- pandas 대신 csv 모듈을 써서 학번 앞자리의 0이 사라지는 문제를 막습니다.
"""
from __future__ import annotations

import csv
import io
import re

REQUIRED_COLUMNS = ["student_no", "name", "main_role", "sub_roles"]
# 보조 역할 구분 문자: 쉼표(,) 세미콜론(;) 세로줄(|) 전각쉼표(，) 모점(、)
# ('/' 는 'UI/UX' 같은 역할 이름에 들어갈 수 있어 구분자로 쓰지 않습니다)
SUB_ROLE_SPLIT = re.compile(r"[,;|，、]+")


def decode_bytes(data: bytes) -> str:
    """UTF-8(BOM 유무 모두) 먼저, 안 되면 엑셀 기본 한글 인코딩(CP949)으로 시도합니다."""
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV 인코딩을 읽을 수 없습니다. UTF-8로 저장해서 다시 올려 주세요.")


def clean_role(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def parse_sub_roles(text: str) -> list:
    roles = []
    for part in SUB_ROLE_SPLIT.split(str(text or "")):
        role = clean_role(part)
        if role and role not in roles:
            roles.append(role)
    return roles


def parse_students(data: bytes):
    """CSV 바이트를 읽어 (학생 목록, 오류 목록)을 돌려줍니다.
    오류가 하나라도 있으면 학생 목록은 비어 있습니다."""
    try:
        text = decode_bytes(data)
    except ValueError as e:
        return [], [str(e)]

    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return [], ["CSV 파일이 비어 있습니다."]

    header = [h.strip().lstrip("\ufeff").lower() for h in rows[0]]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        return [], [f"필수 열이 없습니다: {', '.join(missing)} (필요한 열: {', '.join(REQUIRED_COLUMNS)})"]
    idx = {c: header.index(c) for c in REQUIRED_COLUMNS}

    students, errors, seen = [], [], set()
    for line_no, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue  # 빈 줄 건너뛰기

        def cell(col):
            i = idx[col]
            return row[i].strip() if i < len(row) else ""

        student_no, name, main_role = cell("student_no"), cell("name"), clean_role(cell("main_role"))
        if not student_no or not name or not main_role:
            errors.append(f"{line_no}행: student_no, name, main_role 은 비워 둘 수 없습니다.")
            continue
        if student_no.lower() == "admin":
            errors.append(f"{line_no}행: 학번 'admin' 은 관리자 전용이라 학생 학번으로 쓸 수 없습니다.")
            continue
        if student_no in seen:
            errors.append(f"{line_no}행: 학번 {student_no} 가 중복되었습니다.")
            continue
        seen.add(student_no)
        students.append({
            "student_no": student_no,
            "name": name,
            "main_role": main_role,
            "sub_roles": parse_sub_roles(cell("sub_roles")),
        })

    if errors:
        return [], errors
    if not students:
        return [], ["학생 데이터가 한 줄도 없습니다."]
    return students, []
