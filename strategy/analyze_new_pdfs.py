"""
자산제곱 PDF 자동 분석기
========================
Cowork 스케줄 태스크에서 실행됩니다.

동작:
1. 자산제곱 Obsidian 폴더에서 새 PDF 감지
2. 텍스트 추출
3. processed_pdfs.json에 기록 (중복 처리 방지)
4. current_strategy.md 업데이트
5. GitHub push (앱 자동 반영)
"""

import os
import sys
import json
import unicodedata
import subprocess
from datetime import datetime
from pathlib import Path

# ── 경로 설정 ─────────────────────────────────────────────
MNT_BASE = "/sessions/awesome-wonderful-hawking/mnt/"
PDF_FOLDER_KEYWORD = "자산제곱"
STRATEGY_DIR = os.path.join(MNT_BASE, "자산제곱 AI 분석기 App", "strategy")
PROCESSED_FILE = os.path.join(STRATEGY_DIR, "processed_pdfs.json")
OUTPUT_FILE = os.path.join(STRATEGY_DIR, "current_strategy.md")
REPO_DIR = "/tmp/assetx2_repo"
GITHUB_REPO = "kkyoungh8/assetx2-analyzer"
# PAT은 환경변수 GITHUB_PAT 또는 로컬 설정 파일에서 읽음 (절대 코드에 직접 기재하지 않음)
def _get_github_url():
    pat = os.environ.get("GITHUB_PAT", "")
    if not pat:
        # 로컬 설정 파일에서 읽기 (Cowork 스케줄 태스크 환경)
        cfg = os.path.join(MNT_BASE, "자산제곱 AI 분석기 App", "strategy", ".github_pat")
        if os.path.exists(cfg):
            with open(cfg) as f:
                pat = f.read().strip()
    if not pat:
        raise RuntimeError("GITHUB_PAT 환경변수 또는 .github_pat 파일이 필요합니다.")
    return f"https://{pat}@github.com/{GITHUB_REPO}.git"


def find_pdf_folder():
    """Obsidian PDF 폴더 경로 반환"""
    for item in os.listdir(MNT_BASE):
        normalized = unicodedata.normalize("NFC", item)
        if PDF_FOLDER_KEYWORD in normalized and "AI" not in normalized:
            return os.path.join(MNT_BASE, item)
    raise FileNotFoundError("자산제곱 PDF 폴더를 찾을 수 없습니다.")


def get_all_pdfs(folder):
    """PDF 파일 목록 (mtime, 정규화된 파일명, 원본경로)"""
    results = []
    for fname in os.listdir(folder):
        if not fname.endswith(".pdf"):
            continue
        path = os.path.join(folder, fname)
        mtime = os.path.getmtime(path)
        name_nfc = unicodedata.normalize("NFC", fname)
        results.append((mtime, name_nfc, path))
    return sorted(results, reverse=True)


def load_processed():
    """처리된 PDF 목록 로드"""
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE) as f:
            return set(json.load(f))
    return set()


def save_processed(processed_set):
    """처리된 PDF 목록 저장"""
    os.makedirs(STRATEGY_DIR, exist_ok=True)
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(processed_set), f, ensure_ascii=False, indent=2)


def extract_text(pdf_path, max_chars=5000):
    """PDF 텍스트 추출"""
    try:
        import warnings
        warnings.filterwarnings("ignore")
        from pdfminer.high_level import extract_text as _extract
        text = _extract(pdf_path)
        return text[:max_chars].strip()
    except Exception as e:
        return f"[추출 실패: {e}]"


def push_to_github():
    """GitHub에 변경사항 push"""
    try:
        github_url = _get_github_url()
        # 레포 클론 또는 pull
        if not os.path.exists(os.path.join(REPO_DIR, ".git")):
            subprocess.run(["git", "clone", github_url, REPO_DIR], check=True, capture_output=True)

        subprocess.run(["git", "-C", REPO_DIR, "pull"], capture_output=True)
        subprocess.run(["git", "-C", REPO_DIR, "config", "user.email", "kkyoungh8@gmail.com"], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "config", "user.name", "kkyoungh8"], check=True)

        # strategy 폴더 복사
        import shutil
        dest = os.path.join(REPO_DIR, "strategy")
        os.makedirs(dest, exist_ok=True)
        shutil.copy2(OUTPUT_FILE, dest)

        subprocess.run(["git", "-C", REPO_DIR, "add", "strategy/"], check=True)
        result = subprocess.run(
            ["git", "-C", REPO_DIR, "commit", "-m",
             f"auto: PDF 분석 업데이트 ({datetime.now().strftime('%Y-%m-%d %H:%M')})"],
            capture_output=True, text=True
        )
        if "nothing to commit" not in result.stdout:
            subprocess.run(["git", "-C", REPO_DIR, "push", github_url], check=True, capture_output=True)
            return True
        return False
    except Exception as e:
        print(f"GitHub push 실패: {e}")
        return False


def run():
    """메인 실행"""
    print(f"\n{'='*50}")
    print(f"자산제곱 PDF 분석기 실행: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print('='*50)

    # 1. PDF 폴더 확인
    folder = find_pdf_folder()
    all_pdfs = get_all_pdfs(folder)
    processed = load_processed()

    # 2. 새 PDF 감지
    new_pdfs = [(mtime, name, path) for mtime, name, path in all_pdfs if name not in processed]

    if not new_pdfs:
        print("✅ 새로운 PDF 없음. 종료합니다.")
        return

    print(f"🆕 새 PDF {len(new_pdfs)}개 발견:")
    for _, name, _ in new_pdfs:
        print(f"   - {name}")

    # 3. 최신 3개만 분석 (컨텍스트 토큰 관리)
    to_analyze = sorted(new_pdfs, reverse=True)[:3]
    texts = {}
    for _, name, path in to_analyze:
        print(f"\n📄 추출 중: {name}")
        texts[name] = extract_text(path)
        print(f"   → {len(texts[name])}자 추출")

    # 4. 현재 날짜 기준 전략 파일 생성
    # (실제 운영 시 Claude가 직접 분석 작성)
    today = datetime.now().strftime("%Y-%m-%d")
    pdf_list = "\n".join([f"- {n}" for _, n, _ in to_analyze])

    content = f"""# 자산제곱 현재 전략 컨텍스트
> 최종 업데이트: {today} | 분석 기반 리포트: {', '.join([n[:6] for _, n, _ in to_analyze])}

---

## 📄 분석된 리포트
{pdf_list}

---

## 📋 분석 내용
"""
    for name, text in texts.items():
        content += f"\n### {name}\n\n{text[:2000]}\n\n---\n"

    os.makedirs(STRATEGY_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"\n✅ {OUTPUT_FILE} 저장 완료")

    # 5. 처리 목록 업데이트
    for _, name, _ in new_pdfs:
        processed.add(name)
    save_processed(processed)

    # 6. GitHub push
    print("\n🚀 GitHub push 중...")
    if push_to_github():
        print("✅ GitHub push 완료 → Streamlit 앱 자동 반영")
    else:
        print("ℹ️  변경사항 없거나 push 실패")


if __name__ == "__main__":
    run()
