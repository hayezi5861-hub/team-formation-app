"""규칙 검사 모듈.

이 파일에는 Streamlit이나 데이터베이스와 무관한 '순수 함수'만 모아 두었습니다.
(순수 함수 = 같은 입력이면 항상 같은 결과를 돌려주고, 바깥 세상을 건드리지 않는 함수)
덕분에 DB 없이도 규칙이 맞는지 테스트할 수 있습니다.

과제 규칙과의 대응
- 규칙 10: join_blocker()       -> 같은 주 역할이 있는 팀에는 들어갈 수 없다
- 규칙 15: team_errors()        -> 팀은 최종적으로 2~4명
- 규칙 16: team_errors()        -> 같은 팀에 같은 주 역할 2명 이상 금지
- 규칙 17: has_required_roles()  -> 기획자 1명 + 웹 프로그래머 1명(서로 다른 사람, 보조 역할도 인정)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MIN_TEAM_SIZE = 2
MAX_TEAM_SIZE = 4

# 과제 공고의 역할 이름이 다르면 아래 두 줄만 고치면 됩니다.
PLANNER_ROLE = "기획자"
WEB_ROLE = "웹 프로그래머"


def role_key(role: str) -> str:
    """역할 이름을 비교하기 좋게 정리합니다. (공백 제거 + 소문자)
    예: '웹 프로그래머' 와 '웹프로그래머' 를 같은 역할로 취급합니다."""
    return re.sub(r"\s+", "", str(role or "")).lower()


PLANNER_KEY = role_key(PLANNER_ROLE)
WEB_KEY = role_key(WEB_ROLE)


@dataclass(frozen=True)
class Student:
    """학생 한 명의 정보."""

    student_no: str
    name: str
    main_role: str
    sub_roles: tuple = ()
    # 아래 필드는 __post_init__ 에서 자동 계산됩니다 (직접 넣지 않아도 됨)
    main_key: str = field(init=False, repr=False, compare=False, default="")
    role_keys: frozenset = field(init=False, repr=False, compare=False, default=frozenset())
    can_plan: bool = field(init=False, repr=False, compare=False, default=False)
    can_web: bool = field(init=False, repr=False, compare=False, default=False)

    def __post_init__(self):
        main_key = role_key(self.main_role)
        keys = frozenset({main_key, *(role_key(r) for r in self.sub_roles)})
        object.__setattr__(self, "main_key", main_key)
        object.__setattr__(self, "role_keys", keys)
        object.__setattr__(self, "can_plan", PLANNER_KEY in keys)
        object.__setattr__(self, "can_web", WEB_KEY in keys)

    def can_do(self, role: str) -> bool:
        return role_key(role) in self.role_keys


def has_required_roles(members) -> bool:
    """규칙 17: 기획자 담당 1명 + 웹 프로그래머 담당 1명이 '서로 다른 사람'으로 있는가?
    주 역할뿐 아니라 보조 역할도 인정합니다."""
    planners = [m for m in members if m.can_plan]
    webs = [m for m in members if m.can_web]
    return any(p.student_no != w.student_no for p in planners for w in webs)


def role_coverage(members) -> int:
    """기획/웹 두 자리 중 몇 자리를 서로 다른 사람으로 채울 수 있는지 (0, 1, 2).
    solver.py 가 '앞으로 최소 몇 명이 더 필요한지' 계산할 때 사용합니다."""
    if has_required_roles(members):
        return 2
    if any(m.can_plan or m.can_web for m in members):
        return 1
    return 0


def role_deficit_error(members):
    """'앞날 점검': 지금 팀원들로 볼 때, 남은 자리(최대 4명까지)를 모두 써도
    기획자·웹 프로그래머(서로 다른 사람)를 갖출 수 없다면 그 이유를 돌려줍니다. 가능하면 None.
    예) 이미 3명인데 웹 프로그래머를 맡을 사람이 없고, 새로 들어오는 학생도 웹을 못 하면
        4명이 되어도 규칙 17을 만족할 수 없으므로 미리 막습니다."""
    gap = 2 - role_coverage(members)
    room = MAX_TEAM_SIZE - len(members)
    if gap > room:
        return (f"이 구성이 되면 팀 정원({MAX_TEAM_SIZE}명) 안에서 '{PLANNER_ROLE}'와 '{WEB_ROLE}' 담당을 "
                f"서로 다른 사람으로 갖출 수 없게 됩니다.")
    return None


def join_blocker(members, student: Student):
    """student 가 members 로 이루어진 팀에 들어갈 수 없는 이유를 돌려줍니다. 가능하면 None.
    검사 순서: 이미 팀원 -> 정원(4명) -> 주 역할 중복(규칙 10/16) -> 필수 역할 앞날 점검(규칙 17)."""
    if any(m.student_no == student.student_no for m in members):
        return "이미 이 팀의 팀원입니다."
    if len(members) >= MAX_TEAM_SIZE:
        return f"팀 정원({MAX_TEAM_SIZE}명)이 가득 찼습니다."
    if any(m.main_key == student.main_key for m in members):
        return f"같은 주 역할({student.main_role})을 가진 팀원이 이미 있어 이 팀에는 지원할 수 없습니다."
    return role_deficit_error(list(members) + [student])


def team_errors(members, check_size: bool = True) -> list:
    """팀 한 개의 규칙 위반 목록. 비어 있으면 통과.
    check_size=False 는 '모집 중'처럼 아직 최종 상태가 아닐 때(인원 하한·역할 구성은 보지 않음)."""
    errors = []
    n = len(members)
    if check_size and not (MIN_TEAM_SIZE <= n <= MAX_TEAM_SIZE):
        errors.append(f"인원이 {n}명입니다 ({MIN_TEAM_SIZE}~{MAX_TEAM_SIZE}명이어야 함)")
    if n > MAX_TEAM_SIZE and not check_size:
        errors.append(f"인원이 {n}명으로 정원({MAX_TEAM_SIZE}명)을 넘습니다")
    seen = {}
    for m in members:
        seen.setdefault(m.main_key, []).append(m)
    for group in seen.values():
        if len(group) > 1:
            names = ", ".join(g.name for g in group)
            errors.append(f"주 역할이 같은 학생이 있습니다: {group[0].main_role} ({names})")
    if check_size and not has_required_roles(members):
        errors.append(f"'{PLANNER_ROLE}'와 '{WEB_ROLE}'을 맡을 수 있는 서로 다른 학생이 각각 필요합니다")
    if not check_size:
        deficit = role_deficit_error(members)
        if deficit:
            errors.append(deficit)
    return errors


def validate_assignment(teams: dict, team_names: dict | None = None) -> list:
    """모든 팀의 최종 상태를 검사합니다. teams = {team_id: [Student, ...]}.
    비어 있는 팀(0명)도 '2~4명' 규칙 위반으로 처리합니다."""
    team_names = team_names or {}
    errors = []
    owner = {}
    for team_id in sorted(teams):
        label = team_names.get(team_id, f"{team_id}팀")
        for m in teams[team_id]:
            if m.student_no in owner:
                errors.append(f"{m.name}({m.student_no}) 학생이 {owner[m.student_no]}과 {label}에 중복 소속됩니다")
            owner[m.student_no] = label
        for e in team_errors(teams[team_id]):
            errors.append(f"{label}: {e}")
    return errors


def feasibility_warnings(students, team_count: int) -> list:
    """초기화 전에 '애초에 규칙을 지키는 팀 편성이 불가능해 보이는 명단'인지 빠르게 점검합니다.
    (경고만 하고 막지는 않습니다. 정확한 판단은 solver.py 가 합니다.)"""
    warnings = []
    n = len(students)
    if team_count < 1:
        return ["팀 수는 1 이상이어야 합니다."]
    if n < MIN_TEAM_SIZE * team_count:
        warnings.append(f"학생 {n}명으로는 {team_count}개 팀 모두를 {MIN_TEAM_SIZE}명 이상으로 채울 수 없습니다.")
    if n > MAX_TEAM_SIZE * team_count:
        warnings.append(f"학생 {n}명은 {team_count}개 팀({MAX_TEAM_SIZE}명 상한)에 모두 들어갈 수 없습니다.")
    counts = {}
    for s in students:
        counts.setdefault(s.main_key, []).append(s.main_role)
    for roles in counts.values():
        if len(roles) > team_count:
            warnings.append(f"주 역할 '{roles[0]}' 학생이 {len(roles)}명이라 {team_count}개 팀에 한 명씩도 나눌 수 없습니다.")
    if sum(1 for s in students if s.can_plan) < team_count:
        warnings.append(f"'{PLANNER_ROLE}'을 맡을 수 있는 학생이 팀 수({team_count})보다 적습니다.")
    if sum(1 for s in students if s.can_web) < team_count:
        warnings.append(f"'{WEB_ROLE}'을 맡을 수 있는 학생이 팀 수({team_count})보다 적습니다.")
    return warnings
