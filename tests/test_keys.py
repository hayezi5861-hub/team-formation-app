"""교수님 자동 채점용 key 가 '실제 화면'에 만들어지는지, 버튼을 눌렀을 때 제대로 동작하는지 확인합니다.

진짜 Streamlit 대신 tests/fake_streamlit.py 를 끼워 넣고 app.py 를 그대로 실행합니다.
(같은 key 중복 사용도 진짜 Streamlit 처럼 오류로 잡습니다.)
"""
import ast
import os
import runpy
import sys
import types
import unittest
from pathlib import Path

from core import security, services
from tests.fake_repo import FakeRepo
from tests.fake_streamlit import FakeStreamlit, FakeUpload, RerunSignal, StopSignal
from tests.test_core import ADMIN, roster

ROOT = Path(__file__).resolve().parent.parent

PROFESSOR_KEYS = [
    "login_student_no", "login_password", "login_submit", "whoami", "result",
    "admin_roster_file", "admin_team_count", "admin_start", "admin_close",
    "unassigned", "admin_assign", "assign_status", "admin_confirm",
]

FAKE = None
HOLDER = {}
_saved_modules = {}
_saved_env = {}
TEST_ENV = {"SUPABASE_URL": "https://example.invalid", "SUPABASE_KEY": "test-not-a-real-key",
            "ADMIN_PASSWORD": "test-admin-pw"}


def _purge_project_modules():
    import core
    for name in list(sys.modules):
        if name in ("core.config", "core.db", "app") or name == "views" or name.startswith("views."):
            del sys.modules[name]
    for attr in ("config", "db"):
        core.__dict__.pop(attr, None)


def setUpModule():
    global FAKE
    FAKE = FakeStreamlit()
    for name in ("streamlit", "supabase"):
        _saved_modules[name] = sys.modules.get(name)
    sys.modules["streamlit"] = FAKE
    stub = types.ModuleType("supabase")
    stub.create_client = lambda *a, **k: None
    sys.modules["supabase"] = stub
    for name in list(TEST_ENV) + ["OPENROUTER_API_KEY", "OPENROUTER_MODELS"]:
        _saved_env[name] = os.environ.get(name)
        os.environ.pop(name, None)
    os.environ.update(TEST_ENV)
    _purge_project_modules()
    import core.db as db
    db.get_repo = lambda: HOLDER["repo"]          # 화면이 가짜 메모리 DB 를 쓰게 함


def tearDownModule():
    for name, mod in _saved_modules.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod
    for name, value in _saved_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    _purge_project_modules()


def run_app(clicks=(), inputs=None, max_runs=8):
    """app.py 를 한 번 실행합니다. 버튼을 눌러 st.rerun() 이 일어나면 같은 방식으로 다시 실행합니다."""
    FAKE.clicks = set(clicks)
    FAKE.inputs.update(inputs or {})
    for _ in range(max_runs):
        FAKE.reset_run()
        try:
            runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
        except RerunSignal:
            FAKE.clicks = set()                    # 진짜 Streamlit 처럼, 다시 그릴 때는 버튼이 눌린 상태가 아님
            continue
        except StopSignal:
            pass
        return
    raise AssertionError("st.rerun() 이 끝없이 반복됩니다.")


def as_student(no):
    FAKE.session_state["user"] = {"role": "student", "student_no": str(no), "name": f"학생{str(no)[-2:].lstrip('0')}"}
    FAKE.session_state.pop("_flash", None)


class KeyTestBase(unittest.TestCase):
    def setUp(self):
        FAKE.reset_all()
        HOLDER["repo"] = FakeRepo()
        services.initialize(HOLDER["repo"], ADMIN, roster(), 4)

    @property
    def repo(self):
        return HOLDER["repo"]


class ProfessorKeyNamesTest(unittest.TestCase):
    def test_key_names_are_exactly_as_required(self):
        from core import keys
        self.assertEqual(keys.LOGIN_STUDENT_NO, "login_student_no")
        self.assertEqual(keys.LOGIN_PASSWORD, "login_password")
        self.assertEqual(keys.LOGIN_SUBMIT, "login_submit")
        self.assertEqual(keys.WHOAMI, "whoami")
        self.assertEqual(keys.RESULT, "result")
        self.assertEqual(keys.team(1), "team_1")
        self.assertEqual(keys.team(12), "team_12")
        self.assertEqual(keys.apply(1), "apply_1")
        self.assertEqual(keys.vote_yes("2026001"), "vote_yes_2026001")
        self.assertEqual(keys.vote_no("2026001"), "vote_no_2026001")
        self.assertEqual(keys.ADMIN_ROSTER_FILE, "admin_roster_file")
        self.assertEqual(keys.ADMIN_TEAM_COUNT, "admin_team_count")
        self.assertEqual(keys.ADMIN_START, "admin_start")
        self.assertEqual(keys.ADMIN_CLOSE, "admin_close")
        self.assertEqual(keys.UNASSIGNED, "unassigned")
        self.assertEqual(keys.ADMIN_ASSIGN, "admin_assign")
        self.assertEqual(keys.ASSIGN_STATUS, "assign_status")
        self.assertEqual(keys.ADMIN_CONFIRM, "admin_confirm")

    def test_views_never_use_raw_string_keys(self):
        """화면 파일의 모든 key= 는 core/keys.py 를 거쳐야 합니다 (이름이 한 곳에서만 정의되도록)."""
        checked = 0
        for path in (ROOT / "views").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    for kw in node.keywords:
                        if kw.arg == "key":
                            checked += 1
                            value = kw.value
                            ok = (isinstance(value, ast.Attribute) and getattr(value.value, "id", "") == "keys") or \
                                 (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                                  and getattr(value.func.value, "id", "") == "keys")
                            self.assertTrue(ok, f"{path.name}:{node.lineno} 에서 keys 모듈을 거치지 않은 key 를 씁니다")
        self.assertGreater(checked, 15)
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn('key="', app)


class LoginScreenTest(KeyTestBase):
    def test_login_keys_exist(self):
        run_app()
        for k in ("login_student_no", "login_password", "login_submit"):
            self.assertIn(k, FAKE.keys_run)
        self.assertNotIn("whoami", FAKE.keys_run)

    def test_login_with_initial_password_1234(self):
        run_app(clicks=["login_submit"], inputs={"login_student_no": "20001", "login_password": "1234"})
        self.assertEqual(FAKE.session_state["user"]["student_no"], "20001")
        self.assertIn("whoami", FAKE.keys_run)
        self.assertIn("20001", FAKE.text_of("whoami"))
        self.assertIn("학생1", FAKE.text_of("whoami"))

    def test_wrong_password_and_student_number_as_password_fail(self):
        for pw in ("20001", "wrong", ""):
            FAKE.reset_all()
            run_app(clicks=["login_submit"], inputs={"login_student_no": "20001", "login_password": pw})
            self.assertNotIn("user", FAKE.session_state)
            self.assertTrue(any("올바르지 않습니다" in t for t in FAKE.all_texts) or pw == "")


class StudentScreenTest(KeyTestBase):
    def test_all_student_keys_rendered(self):
        as_student("20001")
        run_app()
        expected = {"whoami", "result"} | {f"team_{n}" for n in range(1, 5)} | {f"apply_{n}" for n in range(1, 5)}
        self.assertTrue(expected <= FAKE.keys_run, expected - FAKE.keys_run)
        self.assertIn("1팀", FAKE.text_of("team_1"))
        self.assertIn("내 팀: 없음", FAKE.text_of("result"))

    def test_apply_vote_yes_and_no_through_the_screen(self):
        as_student("20001")
        run_app(clicks=["apply_1"])                                   # 빈 팀 -> 바로 승인
        self.assertEqual(self.repo.members.get("20001"), 1)
        self.assertIn("합류", FAKE.text_of("result"))
        self.assertIn("내 팀: 1팀", FAKE.text_of("result"))
        self.assertIn("학생1", FAKE.text_of("team_1"))

        as_student("20004")
        run_app(clicks=["apply_1"])                                   # 기존 팀원 있음 -> 투표 대기
        self.assertNotIn("20004", self.repo.members)
        self.assertIn("대기", FAKE.text_of("result"))

        as_student("20001")
        run_app()
        self.assertIn("vote_yes_20004", FAKE.keys_run)
        self.assertIn("vote_no_20004", FAKE.keys_run)
        run_app(clicks=["vote_yes_20004"])
        self.assertEqual(self.repo.members.get("20004"), 1)
        self.assertIn("승인", FAKE.text_of("result"))

        as_student("20007")
        run_app(clicks=["apply_1"])
        as_student("20001")
        run_app()
        self.assertIn("vote_no_20007", FAKE.keys_run)
        run_app(clicks=["vote_no_20007"])                             # 거부 한 명이면 즉시 거절
        self.assertNotIn("20007", self.repo.members)
        self.assertEqual(self.repo.list_applications(student_no="20007")[0]["status"], "rejected")
        self.assertIn("거절", FAKE.text_of("result"))

    def test_errors_are_shown_in_result(self):
        as_student("20001")
        run_app(clicks=["apply_1"])
        run_app(clicks=["apply_2"])                                   # 이미 팀에 속함
        self.assertIn("[error]", FAKE.text_of("result"))
        self.assertIn("이미 팀에 소속", FAKE.text_of("result"))
        as_student("20002")
        run_app(clicks=["apply_1"])                                   # 같은 주 역할(기획자)
        self.assertIn("같은 주 역할", FAKE.text_of("result"))

    def test_apply_after_close_is_refused(self):
        services.close_recruitment(self.repo, ADMIN)
        as_student("20001")
        run_app(clicks=["apply_1"])
        self.assertEqual(self.repo.members, {})
        self.assertIn("[error]", FAKE.text_of("result"))


class AdminScreenTest(KeyTestBase):
    def test_admin_login_and_full_flow_through_the_screen(self):
        run_app(clicks=["login_submit"], inputs={"login_student_no": "admin", "login_password": "test-admin-pw"})
        self.assertEqual(FAKE.session_state["user"]["role"], "admin")
        expected = {"whoami", "admin_roster_file", "admin_team_count", "admin_start", "admin_close",
                    "unassigned", "admin_assign", "assign_status", "admin_confirm"}
        self.assertTrue(expected <= FAKE.keys_run, expected - FAKE.keys_run)

        # 시작: CSV(UTF-8 BOM) 업로드 + 팀 수 -> 초기화
        csv_bytes = (ROOT / "sample_students.csv").read_bytes()
        self.assertTrue(csv_bytes.startswith(b"\xef\xbb\xbf"))
        FAKE.inputs.update({"admin_roster_file": FakeUpload(csv_bytes), "admin_team_count": 4})
        run_app(clicks=["admin_start"])
        self.assertEqual(services.get_phase(self.repo), services.RECRUITING)
        self.assertEqual(len(self.repo.students), 16)
        self.assertEqual(len(self.repo.teams), 4)
        some = next(iter(self.repo.students.values()))
        self.assertTrue(security.verify_password("1234", some["password_hash"]))
        self.assertNotEqual(some["password_hash"], "1234")

        # 학생 일부가 지원한 뒤 마감
        from tests.test_core import ST
        services.apply_to_team(self.repo, ST("2026001"), 1)
        services.apply_to_team(self.repo, ST("2026004"), 2)
        run_app(clicks=["admin_close"])
        self.assertEqual(services.get_phase(self.repo), services.CLOSED)
        self.assertEqual(self.repo.members, {})                       # 각 팀 1명뿐이라 모두 제거
        self.assertIn("팀이 없는 학생 16명", FAKE.text_of("unassigned"))

        # AI 배정 (OpenRouter 설정 없음 -> 앱 자체 탐색)
        run_app(clicks=["admin_assign"])
        self.assertIn("배정안", FAKE.text_of("assign_status"))
        self.assertIn("앱 자체 탐색", FAKE.text_of("assign_status"))
        run_app(clicks=["admin_confirm"])
        self.assertEqual(services.get_phase(self.repo), services.FINALIZED)
        self.assertIn("최종 확정", FAKE.text_of("assign_status"))
        self.assertEqual(len(self.repo.members), 16)

        as_student("2026001")
        run_app()
        self.assertIn("최종 확정", FAKE.text_of("result"))

    def test_no_valid_assignment_is_shown_with_reason(self):
        csv = ("student_no,name,main_role,sub_roles\n"
               "1,가,기획자,\n2,나,기획자,\n3,다,웹 프로그래머,\n4,라,웹 프로그래머,\n5,마,디자이너,\n").encode("utf-8-sig")
        FAKE.session_state["user"] = {"role": "admin", "student_no": "admin", "name": "관리자"}
        FAKE.inputs.update({"admin_roster_file": FakeUpload(csv), "admin_team_count": 1})
        run_app(clicks=["admin_start"])
        run_app(clicks=["admin_close"])
        run_app(clicks=["admin_assign"])
        status = FAKE.text_of("assign_status")
        self.assertIn("규칙을 지키는 배정이 없음", status)
        self.assertIn("5명", status)                                   # 이유 설명
        run_app(clicks=["admin_confirm"])
        self.assertEqual(services.get_phase(self.repo), services.CLOSED)   # 잘못된 결과는 확정되지 않음
        self.assertEqual(self.repo.members, {})

    def test_wrong_role_cannot_open_other_screens(self):
        import views.admin_view as admin_view
        import views.student_view as student_view
        with self.assertRaises(StopSignal):
            admin_view.render({"role": "student", "student_no": "20001", "name": "x"})
        with self.assertRaises(StopSignal):
            student_view.render({"role": "admin", "student_no": "admin", "name": "관리자"})


if __name__ == "__main__":
    unittest.main()
