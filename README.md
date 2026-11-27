# 부자코치

나폴레온 힐 『생각하라 그리고 부자가 되어라』를 바탕으로 한 개인 코칭 앱이다. 자산제곱 투자 관리가 이 앱 안에 들어간다.
설계 문서: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## 맥북에서 처음 실행하기

```bash
# 1) 받기 (저장소가 비공개면 GitHub 로그인 필요)
git clone https://github.com/kkyoungh8/assetx2-analyzer.git
cd assetx2-analyzer
git checkout claude/funny-albattani-rxag36   # main 에 합치기 전까지

# 2) 파이썬 환경 (Python 3.11 이상)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3) API 키 (한 번만)
mkdir -p ~/.richcoach
echo 'ANTHROPIC_API_KEY = "sk-ant-..."' > ~/.richcoach/secrets.toml
chmod 600 ~/.richcoach/secrets.toml

# 4) 실행 → 브라우저에서 http://localhost:8501
streamlit run app.py
```

## 개인 데이터
- 모두 `~/.richcoach/`에 둔다 (저장소 밖이라 git 에 올라가지 않음): `richcoach.db`(SQLite), `secrets.toml`
- 다른 위치를 쓰려면 `RICHCOACH_HOME=/경로 streamlit run app.py`

## 테스트
```bash
pip install pytest
pytest
```
