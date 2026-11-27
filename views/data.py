"""💾 데이터: 위치 안내, 백업·복원"""

import json
from datetime import date

import streamlit as st

from coach import repo
from core import config, ui

conn = ui.conn()

st.title("💾 데이터")
st.markdown(
    f"모든 기록은 맥북의 `{config.db_path()}` 파일(SQLite)에 저장됩니다. 저장소 폴더 밖이라 git 에 올라가지 않습니다.\n\n"
    "Time Machine 을 기본 설정으로 쓰고 있다면 홈 폴더와 함께 백업됩니다. 아래에서 JSON 으로도 내려받을 수 있습니다."
)
st.download_button(
    "⬇️ 백업 내려받기 (JSON)",
    data=json.dumps(repo.export_all(conn), ensure_ascii=False, indent=2).encode("utf-8"),
    file_name=f"richcoach-backup-{date.today().isoformat()}.json",
    mime="application/json", type="primary",
)

st.divider()
up = st.file_uploader("백업 파일로 복원 (지금 기록을 덮어씁니다)", type=["json"])
if up is not None and st.button("이 파일로 덮어쓰기"):
    try:
        repo.import_all(conn, json.loads(up.getvalue().decode("utf-8")))
        st.success("복원했습니다.")
    except (ValueError, KeyError) as e:
        st.error(f"읽을 수 없는 파일입니다: {e}")
