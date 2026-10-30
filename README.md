# 팀 프로젝트 팀 편성 웹 앱

Python · Streamlit · Supabase · OpenRouter 로 만든 팀 편성 앱입니다.

## 파일 구조

```
team-formation-app/
├─ app.py                      # 시작 파일 (로그인 상태에 따라 화면 선택)
├─ requirements.txt            # 설치할 라이브러리 (streamlit>=1.40 필요: st.container(key=...) 사용)
├─ schema.sql                  # Supabase 테이블/제약/트리거 (모든 테이블 tf_ 로 시작)
├─ sample_students.csv         # 연습용 명단 (가상 데이터, 코드에서 사용하지 않음)
├─ .gitignore                  # secrets.toml, .env 를 GitHub 에서 제외
├─ .streamlit/secrets.toml.example   # 비밀 설정 예시 (복사해서 secrets.toml 로 사용)
├─ core/
│   ├─ keys.py                 # ★ 교수님 자동 채점용 Streamlit key 이름 (여기서만 정의)
│   ├─ config.py               # Secrets/환경 변수 읽기
│   ├─ security.py             # 비밀번호 해시(PBKDF2)
│   ├─ csv_loader.py           # CSV(한글, UTF-8 BOM) 읽기
│   ├─ rules.py                # 팀 규칙 검사 (정원, 주 역할 중복, 기획자+웹 프로그래머)
│   ├─ solver.py               # 완전 탐색 배정 + 불가능한 이유 설명
│   ├─ ai_assigner.py          # OpenRouter 호출(모델당 120초) + 응답 검증
│   ├─ services.py             # 지원/투표/마감/AI 배정/확정 + 권한 확인
│   └─ db.py                   # Supabase 읽기/쓰기
├─ views/                      # 화면 (login_view, student_view, admin_view, common)
├─ scripts/
│   ├─ check_secrets.py        # 커밋 전 비밀 정보 검사
│   └─ install_git_hook.sh     # 커밋할 때 자동 검사 설치
└─ tests/                      # 자동 테스트 (Supabase/Streamlit 없이 실행 가능)
    └─ data/                   # 쉬움.csv, 중간.csv, 어려움.csv (연습용 가상 명단)
```

## 필수 Streamlit key
`login_student_no`, `login_password`, `login_submit`, `whoami`, `result`, `team_N`, `apply_N`,
`vote_yes_{지원자 학번}`, `vote_no_{지원자 학번}`, `admin_roster_file`, `admin_team_count`,
`admin_start`, `admin_close`, `unassigned`, `admin_assign`, `assign_status`, `admin_confirm`

- 입력칸·버튼(`login_*`, `apply_N`, `vote_*`, `admin_*`)은 위젯의 `key` 입니다.
- 표시 영역(`whoami`, `result`, `team_N`, `unassigned`, `assign_status`)은 `st.container(key=...)` 로 만들었고,
  HTML 에서는 `class="st-key-이름"` 으로 찾을 수 있습니다.
- 이름 변경은 `core/keys.py` 한 파일에서만 합니다.

## 1. Supabase 준비
1. https://supabase.com 에서 프로젝트를 만든다.
2. **SQL Editor** 에 `schema.sql` 내용을 전부 붙여 넣고 **Run**.
3. **Project Settings > API** 에서 `Project URL` 과 `service_role`(또는 secret) 키를 복사한다.
   - 이 키는 서버(앱)에서만 쓰며, 절대 코드/GitHub 에 쓰지 않는다.

## 2. OpenRouter 준비 (선택)
1. https://openrouter.ai 에서 API 키를 만든다.
2. https://openrouter.ai/models 에서 사용할 텍스트 모델 이름을 최대 3개 고른다.
3. 키/모델을 설정하지 않아도 앱은 동작하며, 이 경우 앱 자체 탐색으로 배정한다.

## 3. 내 컴퓨터에서 실행
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # 열어서 값 채우기
streamlit run app.py
```

## 4. 테스트
```bash
python -m unittest discover -s tests -v
```

## 5. GitHub 업로드 (비밀 정보 보호)
```bash
git init
sh scripts/install_git_hook.sh      # 커밋 때마다 비밀 정보 검사 (선택, 권장)
python scripts/check_secrets.py     # 직접 검사
git add .
git status                          # secrets.toml 이 목록에 없는지 꼭 확인!
git commit -m "team formation app"
git branch -M main
git remote add origin https://github.com/내아이디/저장소이름.git
git push -u origin main
```
이미 키를 커밋했다면 **지우는 것만으로는 부족**합니다(커밋 기록에 남음). 해당 키를 폐기하고 새로 발급받으세요.

## 6. Streamlit Community Cloud 배포
1. https://share.streamlit.io 에서 GitHub 로 로그인 → **Create app**.
2. 저장소/브랜치(main)/Main file path: `app.py`.
3. **Advanced settings > Secrets** 에 `secrets.toml.example` 형식으로 실제 값을 붙여 넣는다.
4. **Deploy**.

## 사용 순서
1. 관리자(`admin` + ADMIN_PASSWORD) 로그인 → CSV 업로드, 팀 수 입력, **명단 등록 및 모집 시작** (학생 초기 비밀번호 = `1234`, DB 에는 해시로 저장)
2. 학생들이 로그인해서 지원/투표
3. 관리자가 **모집 마감** → **팀이 없는 학생 AI 배정** → 결과 확인 → **배정 결과 최종 확정**

## 설계 메모
- 한 학생은 동시에 대기 중인 지원을 1개만 가질 수 있다 (앱 검사 + DB 부분 유니크 인덱스).
- `tf_team_members.student_no` 가 기본키라서 동시에 두 팀에 소속될 수 없고, DB 트리거가 정원(4명)과 같은 주 역할 중복도 한 번 더 막는다.
- 지원할 때와 승인 직전에 정원·주 역할 중복·필수 역할(남은 자리 안에 기획자+웹 프로그래머를 갖출 수 있는지)을 확인한다.
- 솔버가 제한 시간(15초) 안에 결론을 못 내면 "limit" 으로 알리며, 규칙을 어긴 배정은 절대 확정하지 않는다.
