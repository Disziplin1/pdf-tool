"""
PDF 편집기 실행기 (launcher)
  ▸ 고정 경로에 항상 이 작은 실행기만 두고, 실제 프로그램은
    versions\\<버전>\\ 폴더 안에 설치한다.
  ▸ 업데이트 = 새 버전 폴더를 추가하고 current.txt 포인터만 바꾸는 것.
    실행 중인 파일을 직접 덮어쓰지 않으므로 파일 잠금/DLL 문제가 없다.
"""
import sys, os, shutil, subprocess

INSTALL_DIR  = os.path.join(os.environ.get("LOCALAPPDATA", "C:\\Temp"), "PDF편집기")
VERSIONS_DIR = os.path.join(INSTALL_DIR, "versions")
CURRENT_FILE = os.path.join(INSTALL_DIR, "current.txt")
LAUNCHER_EXE = os.path.join(INSTALL_DIR, "PDF 편집기.exe")


def _clean_env():
    env = os.environ.copy()
    env.pop("_MEIPASS2", None)
    if "PATH" in env:
        parts = [p for p in env["PATH"].split(os.pathsep) if "_MEI" not in p]
        env["PATH"] = os.pathsep.join(parts)
    return env


def _fail(msg):
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk(); root.withdraw()
    messagebox.showerror("실행 오류", msg)
    root.destroy()


# ── 최초 설치 (설치 위치 밖에서 실행됐을 때만) ──
def _ensure_installed():
    if not getattr(sys, "frozen", False):
        return
    cur = os.path.normcase(os.path.abspath(sys.executable))
    dst = os.path.normcase(os.path.abspath(LAUNCHER_EXE))
    if cur == dst:
        return  # 이미 설치 위치에서 실행 중

    src_dir = os.path.dirname(sys.executable)
    os.makedirs(INSTALL_DIR, exist_ok=True)
    shutil.copy2(sys.executable, LAUNCHER_EXE)

    # 배포 zip 에 같이 들어있는 초기 버전 폴더/포인터 파일을 설치 위치로 복사
    src_versions = os.path.join(src_dir, "versions")
    src_current  = os.path.join(src_dir, "current.txt")
    if os.path.isdir(src_versions) and not os.path.isdir(VERSIONS_DIR):
        shutil.copytree(src_versions, VERSIONS_DIR)
    if os.path.isfile(src_current) and not os.path.isfile(CURRENT_FILE):
        shutil.copy2(src_current, CURRENT_FILE)

    subprocess.Popen([LAUNCHER_EXE], env=_clean_env())
    sys.exit(0)


# ── 현재 버전 실행 ──
def _launch_current():
    if not os.path.isfile(CURRENT_FILE):
        _fail("설치된 버전을 찾을 수 없습니다.\n프로그램을 다시 다운로드해 주세요.")
        return
    ver = open(CURRENT_FILE, encoding="utf-8").read().strip()
    app_exe = os.path.join(VERSIONS_DIR, ver, "PDF 편집기.exe")
    if not os.path.isfile(app_exe):
        _fail(f"버전 {ver} 실행 파일을 찾을 수 없습니다.\n프로그램을 다시 다운로드해 주세요.")
        return
    # 창 모드(콘솔 없음) 빌드는 sys.stdin/stdout/stderr 가 없어서, 자식
    # 프로세스에 표준 입출력을 그대로 상속시키려다 문제가 생기는 걸
    # 방지하기 위해 명시적으로 끊어준다.
    subprocess.Popen(
        [app_exe], env=_clean_env(),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


if __name__ == "__main__":
    _ensure_installed()
    _launch_current()
