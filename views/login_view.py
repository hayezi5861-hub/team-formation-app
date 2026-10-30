"""로그인 화면. (key: login_student_no, login_password, login_submit)"""
import streamlit as st

from core import config, keys, services


def render(repo) -> None:
    st.title("👥 팀 프로젝트 팀 편성")
    st.caption("학번과 비밀번호로 로그인하세요. 관리자는 학번 admin 으로 로그인합니다.")
    student_no = st.text_input("학번", key=keys.LOGIN_STUDENT_NO)
    password = st.text_input("비밀번호", type="password", key=keys.LOGIN_PASSWORD)
    if st.button("로그인", key=keys.LOGIN_SUBMIT):
        try:
            user = services.authenticate(
                repo, config.ADMIN_ID, str(config.get_secret("ADMIN_PASSWORD", "")), student_no, password)
        except Exception:
            st.error("서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.")
            return
        if user:
            st.session_state["user"] = user
            st.rerun()
        else:
            st.error("학번 또는 비밀번호가 올바르지 않습니다.")
