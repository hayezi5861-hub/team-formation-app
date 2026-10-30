"""학생 화면.

자동 채점 key: whoami, result, team_N, apply_N, vote_yes_{지원자 학번}, vote_no_{지원자 학번}
- whoami : 로그인한 사용자 표시 영역
- result : 내 팀 소속 상태와 가장 최근 지원/투표 결과
- team_N : N번 팀 카드 (팀원, 주 역할, 보조 역할)
- apply_N: N번 팀에 지원하는 버튼
"""
import streamlit as st

from core import keys, services
from core.db import get_repo
from views.common import do_action, member_lines, roles_text, show_flash

STATUS_LABELS = {"pending": "대기 중", "approved": "승인", "rejected": "거절", "cancelled": "취소"}


def render(user: dict) -> None:
    if user.get("role") != "student":          # 권한 분리: 학생 화면은 학생만 (서비스 함수에서도 한 번 더 막습니다)
        st.error("학생만 볼 수 있는 화면입니다.")
        st.stop()

    repo = get_repo()
    me_no = user["student_no"]
    phase = services.get_phase(repo)
    snap = services.snapshot(repo)
    me = snap.students.get(me_no)
    if me is None:
        st.error("명단에서 학생 정보를 찾을 수 없습니다. 로그아웃 후 다시 로그인해 주세요.")
        st.stop()

    st.title("팀 편성")
    with st.container(key=keys.WHOAMI):
        st.markdown(f"**{me.name}** ({me.student_no}) · 주 역할: {me.main_role} · 보조 역할: {roles_text(me)}")
    st.caption(f"현재 단계: **{services.PHASE_LABELS.get(phase, phase)}**")

    _result_section(repo, snap, me_no, phase)
    if phase == services.NOT_INITIALIZED:
        st.info("관리자가 아직 학생 명단과 팀을 만들지 않았습니다.")
        return
    if phase == services.RECRUITING:
        _voting_section(repo, user, me_no)
    _teams_section(repo, snap, user, me_no)
    _my_applications_section(repo, snap, user, me_no, phase)
    _password_section(repo, user)


def _result_section(repo, snap, me_no: str, phase: str) -> None:
    with st.container(key=keys.RESULT):
        my_team = snap.team_of.get(me_no)
        if my_team:
            suffix = " (최종 확정)" if phase == services.FINALIZED else ""
            st.markdown(f"**내 팀: {snap.team_names[my_team]}**{suffix}")
        elif phase == services.FINALIZED:
            st.markdown("**내 팀: 없음** (최종 확정된 팀이 없습니다. 관리자에게 문의하세요)")
        else:
            st.markdown("**내 팀: 없음**")
        apps = repo.list_applications(student_no=me_no)
        if apps:
            last = apps[-1]
            line = f"최근 지원: {snap.team_names.get(last['team_id'], '?')} — {STATUS_LABELS.get(last['status'], last['status'])}"
            if last.get("reason"):
                line += f" ({last['reason']})"
            st.markdown(line)
        show_flash()


def _voting_section(repo, actor: dict, me_no: str) -> None:
    items = services.pending_votes_for(repo, me_no)
    if not items:
        return
    st.subheader("🗳️ 투표가 필요한 지원")
    st.caption("우리 팀에 들어오고 싶어 하는 학생입니다. 팀원 전원이 찬성해야 승인되고, 한 명이라도 거부하면 거절됩니다.")
    for item in items:
        app, who = item["application"], item["applicant"]
        with st.container(border=True):
            st.write(f"**{who.name}** ({who.student_no}) — 주 역할: {who.main_role} / 보조 역할: {roles_text(who)}")
            c1, c2 = st.columns(2)
            vote = None
            if c1.button("찬성", key=keys.vote_yes(who.student_no)):
                vote = True
            if c2.button("거부", key=keys.vote_no(who.student_no)):
                vote = False
            if vote is not None:
                messages = {
                    "approved": ("투표했습니다. 팀원 전원 찬성으로 지원이 승인되었습니다.", "success"),
                    "rejected": ("투표했습니다. 지원이 거절되었습니다.", "info"),
                    "pending": ("투표했습니다. 다른 팀원의 투표를 기다립니다.", "info"),
                }
                do_action(services.cast_vote, repo, actor, app["id"], vote,
                          ok_message=lambda res: messages[res["status"]])


def _teams_section(repo, snap, actor: dict, me_no: str) -> None:
    st.subheader("📋 팀 목록")
    for team_id, name in snap.team_names.items():
        members = snap.members[team_id]
        with st.container(key=keys.team(team_id), border=True):
            st.markdown(f"**{name}** — {len(members)}명")
            st.markdown(member_lines(members, me_no))
            if st.button(f"{name}에 지원하기", key=keys.apply(team_id)):
                do_action(services.apply_to_team, repo, actor, team_id,
                          ok_message=lambda res: (res["message"], "success" if res["status"] == "approved" else "info"))


def _my_applications_section(repo, snap, actor: dict, me_no: str, phase: str) -> None:
    apps = repo.list_applications(student_no=me_no)
    if not apps:
        return
    st.subheader("📨 내 지원 내역")
    for app in reversed(apps):
        votes = repo.list_votes(app["id"])
        text = (f"{snap.team_names.get(app['team_id'], '?')} — {STATUS_LABELS.get(app['status'], app['status'])}"
                f" (찬성 {sum(v['vote'] == 'approve' for v in votes)} / 거부 {sum(v['vote'] == 'reject' for v in votes)})")
        if app.get("reason"):
            text += f" · {app['reason']}"
        c1, c2 = st.columns([4, 1])
        c1.write(text)
        if app["status"] == "pending" and phase == services.RECRUITING:
            if c2.button("지원 취소", key=keys.cancel_apply(me_no)):
                do_action(services.cancel_application, repo, actor, app["id"],
                          ok_message="지원을 취소했습니다.", ok_level="info")


def _password_section(repo, actor: dict) -> None:
    with st.expander("🔑 비밀번호 변경"):
        old = st.text_input("현재 비밀번호", type="password", key=keys.PW_OLD)
        new = st.text_input("새 비밀번호 (4자 이상)", type="password", key=keys.PW_NEW)
        if st.button("비밀번호 변경", key=keys.PW_CHANGE):
            do_action(services.change_password, repo, actor, old, new, ok_message="비밀번호를 변경했습니다.")
