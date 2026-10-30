"""앱의 핵심 업무 로직(지원, 투표, 마감, AI 배정, 확정).

화면(views)은 이 파일의 함수만 부르고, 이 파일은 'repo'(데이터 저장소)를 통해서만 데이터를 읽고 씁니다.
- 실제 앱: repo = core.db.SupabaseRepo
- 테스트: repo = tests.fake_repo.FakeRepo (메모리 DB)
Streamlit을 import 하지 않으므로 화면 없이도 테스트할 수 있습니다.

실패하면 ServiceError(사용자에게 보여 줄 문장)를 발생시킵니다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from core import ai_assigner, rules, solver
from core.rules import Student
from core.security import hash_password, verify_admin_password, verify_password

INITIAL_PASSWORD = "1234"   # 과제 공고 기준 학생 초기 비밀번호 (DB에는 해시로만 저장)
PHASE_KEY = "phase"
ASSIGN_STATUS_KEY = "assign_status"   # 마지막 AI 배정 결과(JSON 문자열)을 보관
NOT_INITIALIZED = "not_initialized"
RECRUITING = "recruiting"   # 모집 중: 지원/투표 가능
CLOSED = "closed"           # 모집 마감: 관리자가 AI 배정 진행
FINALIZED = "finalized"     # 최종 확정

PHASE_LABELS = {
    NOT_INITIALIZED: "초기화 전",
    RECRUITING: "모집 중",
    CLOSED: "모집 마감 (배정 진행 중)",
    FINALIZED: "최종 확정",
}


class ServiceError(Exception):
    """사용자에게 그대로 보여 줘도 되는 오류 메시지."""


# ---------------------------------------------------------------- 권한 확인 (화면 밖에서도 한 번 더 막는 이중 잠금)

def _require_admin(actor) -> None:
    if not actor or actor.get("role") != "admin":
        raise ServiceError("관리자만 사용할 수 있는 기능입니다.")


def _require_student(actor) -> str:
    """학생 본인만 가능한 기능. 학번은 로그인 세션(actor)에서만 가져오므로 남의 이름으로 행동할 수 없습니다."""
    if not actor or actor.get("role") != "student" or not actor.get("student_no"):
        raise ServiceError("학생 계정으로 로그인해야 사용할 수 있는 기능입니다.")
    return actor["student_no"]


def get_assign_status(repo):
    """마지막 AI 배정 결과 {state, message, reasons, logs, source, proposal_id} 또는 None."""
    raw = repo.get_setting(ASSIGN_STATUS_KEY, "")
    try:
        return json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None


def _save_assign_status(repo, **status) -> None:
    repo.set_setting(ASSIGN_STATUS_KEY, json.dumps(status, ensure_ascii=False))


# ---------------------------------------------------------------- 조회

@dataclass
class Snapshot:
    team_names: dict   # {team_id: "1팀"}
    students: dict     # {student_no: Student}
    members: dict      # {team_id: [Student, ...]}
    team_of: dict      # {student_no: team_id}

    @property
    def free(self) -> list:
        """팀이 없는 학생들"""
        return sorted((s for no, s in self.students.items() if no not in self.team_of),
                      key=lambda s: s.student_no)


def to_student(row: dict) -> Student:
    return Student(row["student_no"], row["name"], row["main_role"], tuple(row.get("sub_roles") or ()))


def snapshot(repo) -> Snapshot:
    students = {r["student_no"]: to_student(r) for r in repo.list_students()}
    team_names = {t["id"]: t["name"] for t in repo.list_teams()}
    members = {t: [] for t in team_names}
    team_of = {}
    for m in repo.list_members():
        if m["student_no"] in students and m["team_id"] in members:
            members[m["team_id"]].append(students[m["student_no"]])
            team_of[m["student_no"]] = m["team_id"]
    for t in members:
        members[t].sort(key=lambda s: s.student_no)
    return Snapshot(team_names, students, members, team_of)


def get_phase(repo) -> str:
    return repo.get_setting(PHASE_KEY, NOT_INITIALIZED)


def _require_phase(repo, phase: str) -> None:
    current = get_phase(repo)
    if current != phase:
        raise ServiceError(f"지금은 할 수 없는 작업입니다. (현재 단계: {PHASE_LABELS.get(current, current)}, "
                           f"필요한 단계: {PHASE_LABELS[phase]})")


# ---------------------------------------------------------------- 로그인

def authenticate(repo, admin_id: str, admin_password: str, student_no: str, password: str):
    """로그인 성공하면 {'student_no','name','role'}, 실패하면 None."""
    student_no = (student_no or "").strip()
    if not student_no or not password:
        return None
    if student_no.lower() == admin_id.lower():
        if verify_admin_password(password, admin_password):
            return {"student_no": admin_id, "name": "관리자", "role": "admin"}
        return None
    row = repo.get_student(student_no)
    if row and verify_password(password, row["password_hash"]):
        return {"student_no": row["student_no"], "name": row["name"], "role": "student"}
    return None


def change_password(repo, actor: dict, old: str, new: str) -> None:
    student_no = _require_student(actor)
    row = repo.get_student(student_no)
    if not row or not verify_password(old, row["password_hash"]):
        raise ServiceError("현재 비밀번호가 올바르지 않습니다.")
    if len(new) < 4:
        raise ServiceError("새 비밀번호는 4자 이상이어야 합니다.")
    repo.update_password_hash(student_no, hash_password(new))


# ---------------------------------------------------------------- 관리자: 초기화

def initialize(repo, actor: dict, students: list, team_count: int) -> list:
    """학생 명단과 팀을 초기화합니다. (기존 데이터는 모두 삭제)
    모든 학생의 초기 비밀번호는 '1234' 이며, 해시로 변환해 저장합니다. 경고 목록을 돌려줍니다."""
    _require_admin(actor)
    if team_count < 1:
        raise ServiceError("팀 수는 1 이상이어야 합니다.")
    if not students:
        raise ServiceError("학생 명단이 비어 있습니다.")
    warnings = rules.feasibility_warnings([to_student(s) for s in students], team_count)
    repo.reset_all()
    repo.add_students([{**s, "password_hash": hash_password(INITIAL_PASSWORD)} for s in students])
    repo.create_teams(team_count)
    repo.set_setting("team_count", team_count)
    repo.set_setting(ASSIGN_STATUS_KEY, "")
    repo.set_setting(PHASE_KEY, RECRUITING)
    return warnings


# ---------------------------------------------------------------- 지원 / 투표

def apply_to_team(repo, actor: dict, team_id: int) -> dict:
    """팀에 지원합니다. 빈 팀이면 즉시 승인, 아니면 팀원 투표를 기다립니다(pending).
    지원 시점에 정원, 주 역할 중복, 필수 역할(기획자·웹 프로그래머)을 모두 확인합니다."""
    student_no = _require_student(actor)
    _require_phase(repo, RECRUITING)
    snap = snapshot(repo)
    student = snap.students.get(student_no)
    if student is None:
        raise ServiceError("등록되지 않은 학생입니다.")
    if student_no in snap.team_of:                                     # 규칙 11
        raise ServiceError("이미 팀에 소속되어 있어 다른 팀에 지원할 수 없습니다.")
    if repo.list_applications(student_no=student_no, status="pending"):
        raise ServiceError("이미 대기 중인 지원이 있습니다. 결과를 기다리거나 지원을 취소해 주세요.")
    if team_id not in snap.team_names:
        raise ServiceError("존재하지 않는 팀입니다.")
    members = snap.members[team_id]
    blocker = rules.join_blocker(members, student)                     # 규칙 10 + 정원
    if blocker:
        raise ServiceError(blocker)

    if not members:                                                    # 규칙 9
        app = repo.create_application(student_no, team_id, "pending")
        status = _join_and_verify(repo, app["id"], student, team_id, "빈 팀이라 즉시 승인")
        if status == "approved":
            _reevaluate_pending(repo, team_id, exclude=app["id"])
            return {"status": "approved", "message": f"{snap.team_names[team_id]}에 바로 합류했습니다."}
        raise ServiceError("동시에 다른 지원이 먼저 처리되어 승인되지 않았습니다. 다시 시도해 주세요.")

    repo.create_application(student_no, team_id, "pending")            # 규칙 8: 투표 대기
    return {"status": "pending", "message": "지원했습니다. 기존 팀원 전원의 찬성을 기다리는 중입니다."}


def cancel_application(repo, actor: dict, application_id: int) -> None:
    student_no = _require_student(actor)
    _require_phase(repo, RECRUITING)
    app = repo.get_application(application_id)
    if not app or app["student_no"] != student_no:
        raise ServiceError("본인의 지원만 취소할 수 있습니다.")
    if app["status"] != "pending":
        raise ServiceError("대기 중인 지원만 취소할 수 있습니다.")
    repo.update_application(application_id, "cancelled", "지원자가 취소")


def cast_vote(repo, actor: dict, application_id: int, approve: bool) -> dict:
    """기존 팀원이 지원에 찬성/거부 투표를 합니다."""
    voter_no = _require_student(actor)
    _require_phase(repo, RECRUITING)
    app = repo.get_application(application_id)
    if not app or app["status"] != "pending":
        raise ServiceError("이미 처리되었거나 존재하지 않는 지원입니다.")
    snap = snapshot(repo)
    if snap.team_of.get(voter_no) != app["team_id"]:
        raise ServiceError("해당 팀의 팀원만 투표할 수 있습니다.")
    if any(v["voter_no"] == voter_no for v in repo.list_votes(application_id)):
        raise ServiceError("이미 투표했습니다.")
    repo.add_vote(application_id, voter_no, approve)
    return evaluate_application(repo, application_id)


def evaluate_application(repo, application_id: int) -> dict:
    """대기 중 지원의 현재 결과를 다시 계산합니다.
    - 한 명이라도 거부 -> 거절 (규칙 8)
    - 현재 팀원 전원 찬성 -> 승인
    - 그 사이 팀 사정이 바뀌어 규칙(주 역할 중복, 정원)을 어기게 되면 거절"""
    app = repo.get_application(application_id)
    if not app or app["status"] != "pending":
        return app
    snap = snapshot(repo)
    applicant = snap.students.get(app["student_no"])
    team_id = app["team_id"]
    members = snap.members.get(team_id, [])

    if applicant is None or app["student_no"] in snap.team_of:
        repo.update_application(application_id, "rejected", "지원자가 이미 팀에 소속되어 있음")
        return repo.get_application(application_id)
    blocker = rules.join_blocker(members, applicant)
    if blocker:
        repo.update_application(application_id, "rejected", blocker)
        return repo.get_application(application_id)

    votes = repo.list_votes(application_id)
    if any(v["vote"] == "reject" for v in votes):
        repo.update_application(application_id, "rejected", "팀원이 거부함")
        return repo.get_application(application_id)
    approved = {v["voter_no"] for v in votes if v["vote"] == "approve"}
    if all(m.student_no in approved for m in members):
        if _join_and_verify(repo, application_id, applicant, team_id, "팀원 전원 찬성") == "approved":
            _reevaluate_pending(repo, team_id, exclude=application_id)
    return repo.get_application(application_id)


def _join_and_verify(repo, application_id, student: Student, team_id: int, reason: str) -> str:
    """팀에 추가하고, 동시 처리로 규칙이 깨지지 않았는지 다시 확인합니다."""
    try:
        repo.add_member(student.student_no, team_id)   # DB의 student_no 유일 제약이 중복 소속을 막음 (규칙 11)
    except Exception:
        repo.update_application(application_id, "rejected", "팀 소속 저장 실패(이미 다른 팀에 소속)")
        return "rejected"
    members = snapshot(repo).members[team_id]
    if rules.team_errors(members, check_size=False):
        repo.remove_member(student.student_no)
        repo.update_application(application_id, "rejected", "동시 지원 충돌로 규칙 위반")
        return "rejected"
    repo.update_application(application_id, "approved", reason)
    return "approved"


def _reevaluate_pending(repo, team_id: int, exclude=None) -> None:
    """팀원이 늘면 같은 팀의 다른 대기 지원은 새 팀원의 찬성도 필요하고, 정원/역할 조건도 다시 봐야 합니다."""
    for other in repo.list_applications(team_id=team_id, status="pending"):
        if other["id"] != exclude:
            evaluate_application(repo, other["id"])


def pending_votes_for(repo, student_no: str) -> list:
    """내가 투표해야 하는 지원 목록."""
    snap = snapshot(repo)
    team_id = snap.team_of.get(student_no)
    if team_id is None:
        return []
    items = []
    for app in repo.list_applications(team_id=team_id, status="pending"):
        if any(v["voter_no"] == student_no for v in repo.list_votes(app["id"])):
            continue
        applicant = snap.students.get(app["student_no"])
        if applicant:
            items.append({"application": app, "applicant": applicant})
    return items


# ---------------------------------------------------------------- 관리자: 마감 / 배정 / 확정

def close_recruitment(repo, actor: dict) -> dict:
    """규칙 12: 대기 중 지원은 모두 거절, 1명뿐인 팀의 학생은 팀에서 뺍니다."""
    _require_admin(actor)
    _require_phase(repo, RECRUITING)
    pending = repo.list_applications(status="pending")
    for app in pending:
        repo.update_application(app["id"], "rejected", "모집 마감으로 자동 거절")
    snap = snapshot(repo)
    released = []
    for members in snap.members.values():
        if len(members) == 1:
            repo.remove_member(members[0].student_no)
            released.append(members[0].name)
    repo.set_setting(PHASE_KEY, CLOSED)
    return {"rejected": len(pending), "released": released}


def reopen_recruitment(repo, actor: dict) -> None:
    """(선택 기능) 마감 후 배정이 불가능할 때 모집을 다시 엽니다."""
    _require_admin(actor)
    _require_phase(repo, CLOSED)
    repo.discard_open_proposals()
    repo.set_setting(ASSIGN_STATUS_KEY, "")
    repo.set_setting(PHASE_KEY, RECRUITING)


def generate_proposal(repo, actor: dict, api_key, models, ai_caller=None, max_seconds: float = 15.0) -> dict:
    """팀이 없는 학생의 배정안을 만듭니다. AI(최대 3개 모델) -> 실패 시 완전 탐색.
    어떤 경로든 규칙 검사를 통과한 배정만 '제안'으로 저장됩니다. (확정은 관리자가 따로 합니다)
    실패하면 '규칙을 지키는 배정이 없음'과 그 이유를 assign_status 에 저장합니다."""
    _require_admin(actor)
    _require_phase(repo, CLOSED)
    snap = snapshot(repo)
    free = snap.free
    teams = {t: list(m) for t, m in snap.members.items()}
    logs = []

    if not free:
        assignment, source = {}, "none"
        logs.append("팀이 없는 학생이 없어 배정할 필요가 없습니다.")
    else:
        kwargs = {"caller": ai_caller} if ai_caller else {}
        assignment, model, ai_logs = ai_assigner.run_ai_assignment(
            api_key, models, teams, free, snap.team_names, **kwargs)
        logs += ai_logs
        source = f"ai:{model}"
        if assignment is None:
            logs.append("AI 배정에 실패해 앱 자체 완전 탐색으로 전환합니다.")
            result = solver.solve(teams, free, max_seconds=max_seconds)
            logs.append(result.message)
            if result.status != "found":
                _save_assign_status(repo, state="no_solution" if result.status == "infeasible" else "limit",
                                    message=result.message, reasons=result.reasons, logs=logs)
                return {"ok": False, "proposal": None, "logs": logs, "message": result.message,
                        "reasons": result.reasons}
            assignment, source = result.assignment, "fallback"

    # 어떤 경로로 만들었든 마지막으로 한 번 더 전체 규칙 검사
    merged = {t: list(m) for t, m in teams.items()}
    for no, team_id in assignment.items():
        merged[team_id].append(snap.students[no])
    errors = rules.validate_assignment(merged, snap.team_names)
    if errors:
        _save_assign_status(repo, state="no_solution", message="규칙을 지키는 배정이 없음",
                            reasons=errors, logs=logs)
        return {"ok": False, "proposal": None, "logs": logs, "message": "규칙을 지키는 배정이 없음",
                "reasons": errors}

    repo.discard_open_proposals()
    proposal = repo.save_proposal(source, assignment, [], logs)
    _save_assign_status(repo, state="proposed", message="규칙 검사를 통과한 배정안을 만들었습니다. 확인 후 확정하세요.",
                        reasons=[], logs=logs, source=source, proposal_id=proposal["id"])
    return {"ok": True, "proposal": proposal, "logs": logs, "reasons": [],
            "message": "규칙 검사를 통과한 배정안을 만들었습니다."}


def confirm_proposal(repo, actor: dict, proposal_id: int = None) -> None:
    """관리자가 배정안을 최종 확정합니다. 저장 직전에 현재 상태와 규칙을 다시 검사합니다.
    proposal_id 를 생략하면 가장 최근의 확정 대기 배정안을 사용합니다."""
    _require_admin(actor)
    _require_phase(repo, CLOSED)
    if proposal_id is None:
        latest = repo.latest_proposal()
        if latest is None:
            raise ServiceError("확정할 배정안이 없습니다. 먼저 'AI 배정'으로 배정안을 만들어 주세요.")
        proposal_id = latest["id"]
    proposal = repo.get_proposal(proposal_id)
    if not proposal or proposal["status"] != "proposed":
        raise ServiceError("확정할 수 있는 배정안이 아닙니다. 배정안을 다시 만들어 주세요.")
    snap = snapshot(repo)
    assignment = {str(k): int(v) for k, v in proposal["assignment"].items()}
    if set(assignment) != {s.student_no for s in snap.free}:
        raise ServiceError("배정안을 만든 뒤 팀 구성이 바뀌었습니다. 배정안을 다시 만들어 주세요.")
    merged = {t: list(m) for t, m in snap.members.items()}
    for no, team_id in assignment.items():
        if team_id not in merged:
            raise ServiceError("배정안에 존재하지 않는 팀이 있습니다.")
        merged[team_id].append(snap.students[no])
    errors = rules.validate_assignment(merged, snap.team_names)
    if errors:
        raise ServiceError("규칙 검사에 실패해 확정할 수 없습니다: " + " / ".join(errors[:3]))

    added = []
    try:
        for no, team_id in assignment.items():
            repo.add_member(no, team_id)
            added.append(no)
    except Exception:
        for no in added:        # 중간에 실패하면 되돌림
            repo.remove_member(no)
        raise ServiceError("저장 중 오류가 발생해 확정하지 못했습니다. 다시 시도해 주세요.")
    repo.set_proposal_status(proposal_id, "confirmed")
    _save_assign_status(repo, state="confirmed", message="최종 확정되었습니다.", reasons=[],
                        logs=(get_assign_status(repo) or {}).get("logs", []), proposal_id=proposal_id)
    repo.set_setting(PHASE_KEY, FINALIZED)
