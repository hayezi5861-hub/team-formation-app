"""앱의 시작 파일. 실행: streamlit run app.py

로그인 상태를 확인해서 로그인 화면 / 학생 화면 / 관리자 화면 중 하나를 보여 줍니다.
"""
import streamlit as st

st.set_page_config(page_title="팀 편성 앱", page_icon="👥", layout="wide")

from core import config, keys  # noqa: E402  (set_page_config 뒤에 import)
from core.db import get_repo  # noqa: E402
from views import admin_view, login_view, student_view  # noqa: E402


def main() -> None:
    missing = config.missing_required()
    if missing:
        st.error("설정이 빠져 있습니다: " + ", ".join(missing))
        st.markdown("`.streamlit/secrets.toml` (내 컴퓨터) 또는 Streamlit Cloud의 **Secrets** 에 값을 넣어 주세요. "
                    "예시는 `.streamlit/secrets.toml.example` 파일을 보세요.")
        st.stop()

    try:
        repo = get_repo()
    except Exception:
        st.error("데이터베이스 연결에 실패했습니다. SUPABASE_URL / SUPABASE_KEY 를 확인해 주세요.")
        st.stop()

    user = st.session_state.get("user")
    if not user:
        login_view.render(repo)
        return

    with st.sidebar:
        st.write(f"**{user['name']}** ({user['student_no']})")
        if st.button("로그아웃", key=keys.LOGOUT):
            st.session_state.clear()
            st.rerun()

    if user["role"] == "admin":
        admin_view.render(user)
    else:
        student_view.render(user)


main()
