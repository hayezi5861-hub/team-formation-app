"""Streamlit 위젯/영역 key 이름을 한 곳에 모아 둔 파일. (교수님 자동 채점 프로그램이 찾는 이름)

과제 공고의 필수 key 목록과 '글자 하나까지' 같아야 합니다. 화면 파일(views/*.py)은
이 파일의 상수/함수를 통해서만 key 를 쓰므로, 이름을 바꿀 일이 생기면 여기만 고치면 됩니다.
tests/test_keys.py 가 모든 필수 key 가 실제 화면에 만들어지는지 검사합니다.

종류
- 입력칸·버튼: st.text_input / st.button / st.file_uploader / st.number_input 의 key
- 표시 영역: st.container(key=...) 로 만든 영역 (HTML 에서 class="st-key-이름" 으로 찾을 수 있음)
"""

# ---- 로그인
LOGIN_STUDENT_NO = "login_student_no"     # 학번 입력칸
LOGIN_PASSWORD = "login_password"         # 비밀번호 입력칸
LOGIN_SUBMIT = "login_submit"             # 로그인 버튼

# ---- 로그인 후 공통 / 학생 화면 (표시 영역)
WHOAMI = "whoami"                         # 현재 로그인한 사용자 표시 영역
RESULT = "result"                         # 내 팀 소속 / 지원 결과 표시 영역

# ---- 관리자 화면
ADMIN_ROSTER_FILE = "admin_roster_file"   # 학생 명단 CSV 업로더
ADMIN_TEAM_COUNT = "admin_team_count"     # 팀 수 입력
ADMIN_START = "admin_start"               # 학생 명단/팀 초기화(시작) 버튼
ADMIN_CLOSE = "admin_close"               # 모집 마감 버튼
UNASSIGNED = "unassigned"                 # 팀이 없는 학생 목록 표시 영역
ADMIN_ASSIGN = "admin_assign"             # AI 배정 버튼
ASSIGN_STATUS = "assign_status"           # AI 배정 진행/결과 표시 영역
ADMIN_CONFIRM = "admin_confirm"           # 배정 최종 확정 버튼


# ---- 번호가 붙는 key (team_1, team_2, ... / apply_1, apply_2, ...)
def team(team_id) -> str:
    return f"team_{team_id}"              # 팀 카드 표시 영역


def apply(team_id) -> str:
    return f"apply_{team_id}"             # 해당 팀에 지원하는 버튼


# ---- 투표 버튼: 뒤에 '지원자의 학번'이 붙습니다.
def vote_yes(applicant_student_no) -> str:
    return f"vote_yes_{applicant_student_no}"


def vote_no(applicant_student_no) -> str:
    return f"vote_no_{applicant_student_no}"


# ---- 과제 공고 목록에는 없는 추가 기능용 key (이름이 겹치지 않게 별도 접두어 사용)
LOGOUT = "logout"
ADMIN_REOPEN = "admin_reopen"
CANCEL_PREFIX = "cancel_apply_"
PW_OLD = "pw_old"
PW_NEW = "pw_new"
PW_CHANGE = "pw_change"


def cancel_apply(applicant_student_no) -> str:
    return f"{CANCEL_PREFIX}{applicant_student_no}"


REQUIRED_STATIC = [
    LOGIN_STUDENT_NO, LOGIN_PASSWORD, LOGIN_SUBMIT, WHOAMI, RESULT,
    ADMIN_ROSTER_FILE, ADMIN_TEAM_COUNT, ADMIN_START, ADMIN_CLOSE,
    UNASSIGNED, ADMIN_ASSIGN, ASSIGN_STATUS, ADMIN_CONFIRM,
]
