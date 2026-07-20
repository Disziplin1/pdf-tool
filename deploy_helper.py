import sys, os, shutil, subprocess

def run(cmd):
    return subprocess.run(cmd, shell=True)

mode = sys.argv[1] if len(sys.argv) > 1 else ''
ver  = sys.argv[2] if len(sys.argv) > 2 else ''

if mode == 'git':
    run('git add -A')
    r = run(f'git commit -m "v{ver}"')
    run('git push origin main')

elif mode == 'release':
    src = os.path.join('dist', 'PDF 편집기.exe')
    tmp = os.path.join('dist', 'PDF_Editor.exe')
    shutil.copy2(src, tmp)
    run(f'gh release delete "v{ver}" --yes')
    r = run(
        f'gh release create "v{ver}" "{tmp}" '
        f'--title "PDF Editor v{ver}" --notes "auto deploy"'
    )
    os.remove(tmp)
    sys.exit(r.returncode)
