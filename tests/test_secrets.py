"""API 키, DB 주소, 관리자 비밀번호가 코드/저장소 파일에 노출되지 않는지 확인합니다."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_secrets  # noqa: E402


class SecretsTest(unittest.TestCase):
    def test_project_files_contain_no_secrets(self):
        results = check_secrets.scan_paths()
        self.assertEqual(results, [], results)

    def test_scanner_detects_leaks(self):
        fake_key = "sk-or-" + "v1-" + "a1b2c3d4e5f6a7b8c9d0e1f2"                  # 가짜 값 (코드에 통째로 쓰지 않으려고 쪼갬)
        fake_jwt = "eyJ" + "hbGciOiJIUzI1NiIsInR5" + "." + "eyJpc3MiOiJzdXBhYmFzZSIsInJvbGUiOi" + "." + "abcDEF1234567890xyz"
        fake_url = "https://" + "abcdefghijklmnopqrst" + ".supabase.co"
        self.assertTrue(check_secrets.scan_text(f'key = "{fake_key}"'))
        self.assertTrue(check_secrets.scan_text(f"token: {fake_jwt}"))
        self.assertTrue(check_secrets.scan_text(f'URL = "{fake_url}"'))
        name = "ADMIN_" + "PASSWORD"                                                # 스캐너가 이 테스트 파일을 오탐하지 않도록 쪼갬
        self.assertTrue(check_secrets.scan_text(name + ' = "진짜비밀번호"'))
        self.assertEqual(check_secrets.scan_text(name + ' = "여기에_관리자_비밀번호"'), [])   # 예시 자리표시자는 통과

    def test_code_reads_secrets_only_from_env_or_secrets(self):
        config = (ROOT / "core" / "config.py").read_text(encoding="utf-8")
        self.assertIn("os.environ", config)
        self.assertIn("st.secrets", config)
        for path in list((ROOT / "core").glob("*.py")) + list((ROOT / "views").glob("*.py")) + [ROOT / "app.py"]:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"ADMIN_PASSWORD\s*=\s*[\"']", text), path.name)

    def test_gitignore_blocks_secret_files_but_keeps_example(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in (".streamlit/secrets.toml", ".env"):
            self.assertIn(pattern, ignore)
        self.assertTrue((ROOT / ".streamlit" / "secrets.toml.example").exists())
        self.assertFalse((ROOT / ".streamlit" / "secrets.toml").exists())

    def test_passwords_never_stored_in_plain_text(self):
        from core import services
        from tests.fake_repo import FakeRepo
        from tests.test_core import ADMIN, roster
        repo = FakeRepo()
        services.initialize(repo, ADMIN, roster(), 4)
        for row in repo.students.values():
            self.assertNotEqual(row["password_hash"], "1234")
            self.assertTrue(row["password_hash"].startswith("pbkdf2_sha256$"))


if __name__ == "__main__":
    unittest.main()
