"""화면들이 함께 쓰는 작은 도구 모음."""
from __future__ import annotations

import logging

import streamlit as st

from core import services

log = logging.getLogger(__name__)


def flash(message: str, level: str = "success") -> None:
    """다음 화면(st.rerun 이후)에 한 번만 보여 줄 메시지를 저장합니다. level: success/info/warning/error"""
    st.session_state["_flash"] = (level, message)


def show_flash() -> None:
    item = st.session_state.pop("_flash", None)
    if item:
        level, message = item
        getattr(st, level)(message)


def do_action(action, *args, ok_message="완료했습니다.", ok_level="success", **kwargs) -> None:
    """서비스 함수를 실행하고, 성공/실패 결과를 flash 로 저장한 뒤 화면을 새로 그립니다.
    ok_message 는 문장 또는 '결과를 받아 (문장, 레벨)을 돌려주는 함수' 입니다.
    (st.rerun 은 이 함수 안에서 항상 마지막에 한 번만 호출됩니다.)"""
    try:
        result = action(*args, **kwargs)
    except services.ServiceError as e:
        flash(str(e), "error")
    except Exception:
        log.exception("예상하지 못한 오류")
        flash("서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요. (계속되면 관리자에게 알려 주세요)", "error")
    else:
        if callable(ok_message):
            message, level = ok_message(result)
        else:
            message, level = ok_message, ok_level
        flash(message, level)
    st.rerun()


def roles_text(student) -> str:
    return ", ".join(student.sub_roles) if student.sub_roles else "없음"


def member_lines(members, me_no: str | None = None, show_no: bool = False) -> str:
    """팀원 목록을 마크다운 글줄로 만듭니다. (표 대신 글줄을 써서 화면 글자를 그대로 읽을 수 있게 함)"""
    if not members:
        return "_아직 팀원이 없습니다._"
    lines = []
    for m in members:
        who = f"{m.name} ({m.student_no})" if show_no else m.name
        if m.student_no == me_no:
            who += " (나)"
        lines.append(f"- **{who}** · 주 역할: {m.main_role} · 보조 역할: {roles_text(m)}")
    return "\n".join(lines)
