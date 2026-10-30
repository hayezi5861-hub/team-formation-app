#!/bin/sh
# 커밋할 때마다 비밀 정보 검사를 자동으로 실행하는 git 훅을 설치합니다. (프로젝트 폴더에서 한 번만 실행)
#   sh scripts/install_git_hook.sh
set -e
if [ ! -d .git ]; then
  echo "먼저 'git init' 으로 저장소를 만든 뒤 실행하세요."; exit 1
fi
cat > .git/hooks/pre-commit <<'HOOK'
#!/bin/sh
python scripts/check_secrets.py --staged || python3 scripts/check_secrets.py --staged
HOOK
chmod +x .git/hooks/pre-commit
echo "설치 완료: 이제 git commit 할 때 비밀 정보가 있으면 커밋이 막힙니다."
