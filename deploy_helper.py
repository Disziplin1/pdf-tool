import sys, os, shutil, subprocess, zipfile

def run(cmd):
    return subprocess.run(cmd, shell=True)

mode = sys.argv[1] if len(sys.argv) > 1 else ''
ver  = sys.argv[2] if len(sys.argv) > 2 else ''

APP_DIR      = os.path.join('dist', 'PDF 편집기')       # pdf_tool.spec (onedir) 출력
LAUNCHER_EXE = os.path.join('dist', 'PDF 편집기.exe')   # launcher.spec (onefile) 출력

if mode == 'clean_stale_version':
    # 이전 배포.bat 실행이 VERSION 갱신 후 어느 단계(빌드 등)에서 실패해
    # 커밋되지 못한 채로 남으면, 다음 실행의 git pull 이 "로컬 변경사항이
    # 덮어써진다"며 막힌다. pdf_tool.py 의 미커밋 변경이 VERSION 줄 뿐이면
    # 안전하게 되돌리고, 그 외 다른 내용까지 섞여 있으면(=진짜 작업 중인
    # 변경일 수 있음) 절대 건드리지 않고 실패로 끝낸다.
    diff = subprocess.run(['git', 'diff', '--', 'pdf_tool.py'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace').stdout
    changed = [l for l in diff.splitlines()
               if (l.startswith('+') or l.startswith('-'))
               and not l.startswith('+++') and not l.startswith('---')]
    if not changed:
        print('[clean_stale_version] 되돌릴 변경사항 없음.')
        sys.exit(0)
    only_version = all(l[1:].lstrip().startswith('VERSION') for l in changed)
    if only_version:
        run('git checkout -- pdf_tool.py')
        print('[clean_stale_version] pdf_tool.py 의 미커밋 VERSION 변경(이전 실패한 배포 잔재)만 되돌림.')
        sys.exit(0)
    print('[clean_stale_version] pdf_tool.py 에 VERSION 외 다른 미커밋 변경이 있어 자동으로 되돌리지 않음:')
    print(diff)
    sys.exit(1)

elif mode == 'git':
    run('git add -A')
    r = run(f'git commit -m "v{ver}"')
    run('git push origin main')

elif mode == 'package':
    # ── 업데이트용 zip: onedir 폴더 전체를 그대로 압축 ──
    update_zip = os.path.join('dist', 'PDF_Editor_Update.zip')
    if os.path.exists(update_zip):
        os.remove(update_zip)
    with zipfile.ZipFile(update_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(APP_DIR):
            for name in files:
                full = os.path.join(root, name)
                rel  = os.path.relpath(full, APP_DIR)
                zf.write(full, rel)

    # ── 신규 설치용 zip: 실행기 + 초기 버전 폴더 + current.txt ──
    setup_dir = os.path.join('dist', '_setup_stage')
    if os.path.isdir(setup_dir):
        shutil.rmtree(setup_dir)
    os.makedirs(setup_dir)
    shutil.copy2(LAUNCHER_EXE, os.path.join(setup_dir, 'PDF 편집기.exe'))
    shutil.copytree(APP_DIR, os.path.join(setup_dir, 'versions', ver))
    with open(os.path.join(setup_dir, 'current.txt'), 'w', encoding='utf-8') as f:
        f.write(ver)

    setup_zip = os.path.join('dist', 'PDF_Editor_Setup.zip')
    if os.path.exists(setup_zip):
        os.remove(setup_zip)
    with zipfile.ZipFile(setup_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(setup_dir):
            for name in files:
                full = os.path.join(root, name)
                rel  = os.path.relpath(full, setup_dir)
                zf.write(full, rel)
    shutil.rmtree(setup_dir)
    print(f'생성됨: {update_zip}, {setup_zip}')

elif mode == 'release':
    update_zip = os.path.join('dist', 'PDF_Editor_Update.zip')
    setup_zip  = os.path.join('dist', 'PDF_Editor_Setup.zip')
    run(f'gh release delete "v{ver}" --yes')
    r = run(
        f'gh release create "v{ver}" "{update_zip}" "{setup_zip}" '
        f'--title "PDF Editor v{ver}" --notes "auto deploy"'
    )
    sys.exit(r.returncode)
