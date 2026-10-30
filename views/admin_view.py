"""관리자 화면. (탭을 쓰지 않고 위에서 아래로 한 화면에 모두 보여 줍니다)

자동 채점 key: admin_roster_file, admin_team_count, admin_start, admin_close,
               unassigned, admin_assign, assign_status, admin_confirm   (+ whoami)
"""
import streamlit as st

from core import config, csv_loader, keys, rules, services
from core.db import get_repo
from views.common import do_action, member_lines, roles_text, show_flash

STATE_LABELS = {
    "proposed": "✅ 배정안 생성됨 (확정 대기)",
    "no_solution": "❌ 규칙을 지키는 배정이 없음",
    "limit": "⏱️ 탐색 시간 초과 (결론 못 냄)",
    "confirmed": "🔒 최종 확정 완료",
}


def render(user: dict) -> None:
    if user.get("role") != "admin":            # 권한 분리: 관리자 화면은 관리자만 (서비스 함수에서도 한 번 더 막습니다)
        st.error("관리자만 볼 수 있는 화면입니다.")
        st.stop()

    repo = get_repo()
    phase = services.get_phase(repo)
    snap = services.snapshot(repo)

    st.title("🛠️ 관리자")
    with st.container(key=keys.WHOAMI):
        st.markdown(f"**관리자** ({user['student_no']})")
    st.caption(f"현재 단계: **{services.PHASE_LABELS.get(phase, phase)}**")
    show_flash()

    _init_section(repo, user, phase)
    _close_section(repo, user, phase)
    _unassigned_section(snap, phase)
    _assign_section(repo, user, snap, phase)
    _overview_section(repo, snap)


# ------------------------------------------------------------------ 1. 초기화
def _init_section(repo, actor: dict, phase: str) -> None:
    st.header("1. 학생 명단 · 팀 초기화")
    st.warning("시작(초기화)하면 기존 학생, 팀, 지원, 투표, 배정안이 모두 삭제됩니다. 모든 학생의 초기 비밀번호는 1234 입니다.")
    uploaded = st.file_uploader("학생 명단 CSV (열: student_no, name, main_role, sub_roles)",
                                type=["csv"], key=keys.ADMIN_ROSTER_FILE)
    team_count = int(st.number_input("팀 수", min_value=1, max_value=50, value=4, step=1,
                                     key=keys.ADMIN_TEAM_COUNT))
    students, errors = [], []
    if uploaded is not None:
        students, errors = csv_loader.parse_students(uploaded.getvalue())
        if errors:
            for e in errors[:10]:
                st.error(e)
        else:
            st.success(f"학생 {len(students)}명을 읽었습니다.")
            for w in rules.feasibility_warnings([services.to_student(s) for s in students], team_count):
                st.warning(w)
    if st.button("명단 등록 및 모집 시작", key=keys.ADMIN_START):
        if uploaded is None:
            do_action(_fail, "CSV 파일을 먼저 올려 주세요.")
        elif errors:
            do_action(_fail, "CSV 오류를 고친 뒤 다시 올려 주세요: " + " / ".join(errors[:3]))
        else:
            def done(warnings):
                msg = f"학생 {len(students)}명, 팀 {team_count}개로 초기화했습니다. 모집을 시작합니다."
                if warnings:
                    return msg + " ⚠️ " + " / ".join(warnings), "warning"
                return msg, "success"
            do_action(services.initialize, repo, actor, students, team_count, ok_message=done)


def _fail(message: str):
    raise services.ServiceError(message)


# ------------------------------------------------------------------ 2. 모집 마감
def _close_section(repo, actor: dict, phase: str) -> None:
    st.header("2. 모집 마감")
    st.write("마감하면 ① 대기 중인 모든 지원이 거절되고 ② 팀원이 1명뿐인 팀의 학생은 팀에서 빠집니다. 이후 지원·투표는 할 수 없습니다.")
    if st.button("모집 마감", key=keys.ADMIN_CLOSE):
        def done(info):
            msg = f"모집을 마감했습니다. 거절된 대기 지원 {info['rejected']}건."
            if info["released"]:
                msg += f" 1명뿐인 팀에서 빠진 학생: {', '.join(info['released'])}"
            return msg, "success"
        do_action(services.close_recruitment, repo, actor, ok_message=done)
    if phase == services.CLOSED:
        st.caption("배정이 불가능한 경우에는 모집을 다시 열어 팀 구성을 바꿀 수 있습니다.")
        if st.button("모집 재개", key=keys.ADMIN_REOPEN):
            do_action(services.reopen_recruitment, repo, actor, ok_message="모집을 다시 열었습니다.", ok_level="info")


# ------------------------------------------------------------------ 3. 팀이 없는 학생
def _unassigned_section(snap, phase: str) -> None:
    st.header("3. 팀이 없는 학생")
    with st.container(key=keys.UNASSIGNED):
        if phase == services.NOT_INITIALIZED:
            st.markdown("_아직 명단이 없습니다._")
            return
        free = snap.free
        st.markdown(f"**팀이 없는 학생 {len(free)}명**")
        if free:
            st.markdown("\n".join(
                f"- {s.student_no} {s.name} · 주 역할: {s.main_role} · 보조 역할: {roles_text(s)}" for s in free))


# ------------------------------------------------------------------ 4. AI 배정 · 확정
def _assignment_lines(snap, assignment: dict) -> str:
    out = []
    for team_id, name in snap.team_names.items():
        out.append(f"**{name}**")
        for m in snap.members[team_id]:
            out.append(f"- {m.student_no} {m.name} · {m.main_role} / {roles_text(m)} (기존 팀원)")
        for no, t in assignment.items():
            if t == team_id:
                s = snap.students[no]
                out.append(f"- ⭐ {s.student_no} {s.name} · {s.main_role} / {roles_text(s)} (새로 배정)")
    return "\n".join(out)


def _assign_section(repo, actor: dict, snap, phase: str) -> None:
    st.header("4. AI 배정 · 최종 확정")
    models = config.openrouter_models()
    st.caption(f"AI 모델(순서대로 최대 3개, 모델당 120초 제한): "
               f"{', '.join(models) if models else '설정 없음 → 앱 자체 탐색만 사용'}  |  배정 대상: {len(snap.free)}명")

    if st.button("팀이 없는 학생 AI 배정", key=keys.ADMIN_ASSIGN):
        def done(out):
            return ("규칙 검사를 통과한 배정안을 만들었습니다. 아래에서 확인한 뒤 확정하세요.", "success") if out["ok"] \
                else (out["message"], "error")
        with st.spinner("배정안을 만드는 중입니다... (AI 응답을 기다리는 데 시간이 걸릴 수 있습니다)"):
            do_action(services.generate_proposal, repo, actor, config.openrouter_api_key(), models, ok_message=done)

    status = services.get_assign_status(repo)
    with st.container(key=keys.ASSIGN_STATUS):
        if not status:
            st.markdown("아직 AI 배정을 실행하지 않았습니다.")
        else:
            st.markdown(f"**{STATE_LABELS.get(status['state'], status['state'])}** — {status['message']}")
            if status.get("source"):
                st.markdown(f"만든 방법: {'앱 자체 탐색(AI 실패 후 대체)' if status['source'] == 'fallback' else status['source']}")
            if status.get("reasons"):
                st.markdown("**이유**\n" + "\n".join(f"- {r}" for r in status["reasons"]))
            if status.get("logs"):
                with st.expander("배정 과정 기록"):
                    st.markdown("\n".join(f"- {line}" for line in status["logs"]))

    proposal = repo.latest_proposal() if phase == services.CLOSED else None
    if proposal:
        assignment = {str(k): int(v) for k, v in proposal["assignment"].items()}
        merged = {t: list(m) for t, m in snap.members.items()}
        for no, t in assignment.items():
            if no in snap.students and t in merged:
                merged[t].append(snap.students[no])
        errors = rules.validate_assignment(merged, snap.team_names)
        if errors:
            st.error("규칙 검사 실패 (확정할 수 없습니다): " + " / ".join(errors))
        else:
            st.success("모든 규칙 검사를 통과했습니다. (모든 팀 2~4명, 주 역할 중복 없음, 기획자·웹 프로그래머 포함)")
        st.markdown(_assignment_lines(snap, assignment))

    if st.button("배정 결과 최종 확정", key=keys.ADMIN_CONFIRM):
        do_action(services.confirm_proposal, repo, actor, ok_message="팀 편성을 최종 확정했습니다.")


# ------------------------------------------------------------------ 전체 현황
def _overview_section(repo, snap) -> None:
    st.header("전체 현황")
    if not snap.team_names:
        st.info("아직 초기화되지 않았습니다.")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("전체 학생", len(snap.students))
    c2.metric("팀 소속", len(snap.team_of))
    c3.metric("팀 없음", len(snap.free))
    for team_id, name in snap.team_names.items():
        members = snap.members[team_id]
        errs = rules.team_errors(members)
        with st.container(key=keys.team(team_id), border=True):
            st.markdown(f"**{name}** — {len(members)}명" + ("" if not errs else "  ⚠️ 최종 규칙 미충족: " + " / ".join(errs)))
            st.markdown(member_lines(members, show_no=True))

    st.subheader("지원 · 투표 기록")
    votes = repo.list_votes()
    rows = []
    for a in repo.list_applications():
        who = snap.students.get(a["student_no"])
        vs = [v for v in votes if v["application_id"] == a["id"]]
        rows.append({
            "지원 번호": a["id"], "지원자": f"{who.name if who else '?'}({a['student_no']})",
            "팀": snap.team_names.get(a["team_id"], "?"), "상태": a["status"], "사유": a.get("reason") or "",
            "투표": ", ".join(f"{v['voter_no']}:{'찬성' if v['vote'] == 'approve' else '거부'}" for v in vs),
        })
    st.dataframe(rows, hide_index=True)
