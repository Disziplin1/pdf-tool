"""
PDF 도구  ·  무료 · 오프라인 · 완전 로컬
  ▸ 정리 탭  : 드래그 정렬 · 체크박스 · 호버 툴바 · 미리보기 + 편집
  ▸ 변환 탭  : PDF → 이미지 / 이미지 → PDF
"""
import sys, os, shutil, subprocess, threading, zipfile, math, tempfile, copy

VERSION = "20260831.1215"                       # 배포.bat 이 자동 업데이트
GITHUB_REPO  = "Disziplin1/pdf-tool"

# 실행기(launcher.py)가 관리하는 설치 구조:
#   INSTALL_DIR\PDF 편집기.exe   ← 실행기 (거의 안 바뀜, 고정 경로)
#   INSTALL_DIR\current.txt     ← 현재 사용 중인 버전 문자열
#   INSTALL_DIR\versions\<버전>\PDF 편집기.exe  ← 실제 프로그램(이 파일)
INSTALL_DIR  = os.path.join(os.environ.get("LOCALAPPDATA", "C:\\Temp"), "PDF편집기")
VERSIONS_DIR = os.path.join(INSTALL_DIR, "versions")
CURRENT_FILE = os.path.join(INSTALL_DIR, "current.txt")
LAUNCHER_EXE = os.path.join(INSTALL_DIR, "PDF 편집기.exe")

def _resource_path(name):
    # PyInstaller onedir 은 exe 옆(onedir 구조에서는 _internal 폴더)에서 데이터 파일을 찾음
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def _clean_env():
    env = os.environ.copy()
    env.pop("_MEIPASS2", None)
    if "PATH" in env:
        parts = [p for p in env["PATH"].split(os.pathsep) if "_MEI" not in p]
        env["PATH"] = os.pathsep.join(parts)
    return env


# ── GitHub 업데이트 확인 ──────────────────────────────────────
def _check_update(root):
    def _worker():
        try:
            import urllib.request, json
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            req = urllib.request.Request(url, headers={"User-Agent": "pdf-tool-updater"})
            with urllib.request.urlopen(req, timeout=6) as r:
                data = json.loads(r.read())
            latest = data["tag_name"].lstrip("v")
            if latest <= VERSION:
                return
            assets  = data.get("assets", [])
            dl_url  = next((a["browser_download_url"] for a in assets
                            if a["name"].endswith("_Update.zip")), None)
            if not dl_url:
                return
            root.after(0, lambda: _offer_update(root, latest, dl_url))
        except Exception:
            pass
    threading.Thread(target=_worker, daemon=True).start()

def _offer_update(root, ver, url):
    from tkinter import messagebox as _mb
    if _mb.askyesno("업데이트", f"새 버전 v{ver} 이 있습니다.\n지금 업데이트 하시겠습니까?", parent=root):
        _apply_update(root, ver, url)

def _apply_update(root, ver, url):
    from tkinter import messagebox as _mb
    try:
        import urllib.request
        tmp_zip = os.path.join(os.environ.get("TEMP", "C:\\Temp"), f"pdf_tool_update_{ver}.zip")
        urllib.request.urlretrieve(url, tmp_zip)

        # 실행 중인 파일은 전혀 건드리지 않고, 완전히 새로운 버전 폴더에
        # 압축을 푼다 — 파일 잠금/DLL 문제가 구조적으로 생길 수 없다.
        new_dir = os.path.join(VERSIONS_DIR, ver)
        if os.path.isdir(new_dir):
            shutil.rmtree(new_dir)
        os.makedirs(new_dir, exist_ok=True)
        with zipfile.ZipFile(tmp_zip) as zf:
            zf.extractall(new_dir)
        os.remove(tmp_zip)

        new_exe = os.path.join(new_dir, "PDF 편집기.exe")
        if not os.path.isfile(new_exe):
            raise RuntimeError("업데이트 파일 압축 해제에 실패했습니다.")

        with open(CURRENT_FILE, "w", encoding="utf-8") as f:
            f.write(ver)

        _mb.showinfo("업데이트 완료",
            f"v{ver} 로 업데이트되었습니다.\n프로그램을 다시 시작합니다.", parent=root)

        # 실행기(launcher)는 이번 업데이트로 바뀌지 않은 안정적인 파일이므로,
        # 실행기를 통해 재실행하면 곧바로 열어도 문제가 없다.
        subprocess.Popen([LAUNCHER_EXE], env=_clean_env())
        root.destroy()
    except Exception as e:
        _mb.showerror("업데이트 오류", str(e), parent=root)

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os, itertools
from pypdf import PdfReader, PdfWriter

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_OK = True
except ImportError:
    DND_OK = False

try:
    import fitz
    from PIL import Image, ImageTk, ImageOps
    PREVIEW_OK = True
except ImportError:
    PREVIEW_OK = False

_id_gen = itertools.count()

# ══════════════════════════════════════════════════════════
#  UI 테마  (메인 컬러 #C0392B 계열)
# ══════════════════════════════════════════════════════════
BG       = "#F2F1EF"   # 창 배경 (아주 밝은 회색)
PANEL    = "#FFFFFF"   # 패널 (헤더 · 하단 컨트롤 바)
TOOLBAR  = "#EAE7E5"   # 툴바 (창 배경과 살짝 다른 밝기)
CARD     = "#FFFFFF"   # 카드 / 파일 영역
CARD_CHK = "#FDEDEC"   # 선택 카드 (Light Background)
ACCENT   = "#C0392B"   # Primary
ACCENT_L = "#A93226"   # Hover
ACCENT_D = "#922B21"   # Pressed
TEXT     = "#2B2B2B"   # 본문 텍스트 (짙은 회색)
TEXT_DIM = "#8A8A8A"   # 보조 텍스트
BORDER   = "#E6B0AA"   # 테두리
SUCCESS  = "#30d158"   # (미사용 — 이전 iOS 초록, 하위 호환을 위해 유지)
DANGER   = "#ff3b30"   # 삭제 등 위험 동작 (기존 유지)
DROPH    = "#FDEDEC"   # 드래그오버 (Light Background)
INSLINE  = "#C0392B"
SH1      = "#D9D6D4"   # 그림자 (진)
SH2      = "#EAE8E6"   # 그림자 (연)

FM     = "맑은 고딕"
FONT   = (FM, 10)
FONT_B = (FM, 10, "bold")
FONT_SB= (FM, 11, "bold")   # Semi Bold 대체 (탭용)
FONT_H = (FM, 14, "bold")
FONT_S = (FM, 9)
FONT_XS= (FM, 8)

# 텍스트 annot 기본값 (Phase 3 에서 만든 annot 에는 이 필드들이 없을 수
# 있으므로, 항상 .get(key, DEFAULT_*) 형태로 읽어 하위 호환을 유지한다)
DEFAULT_ANNOT_FONT  = FM
DEFAULT_ANNOT_SIZE  = 50.0     # pt
DEFAULT_ANNOT_COLOR = "#000000"
DEFAULT_ANNOT_TEXT  = "텍스트"  # 새 텍스트 생성 시 기본 내용(바로 선택되어 덮어쓰기 가능)

# 도형(사각형/화살표/강조) annot 기본값
DEFAULT_SHAPE_LINE_COLOR = "#000000"
DEFAULT_RECT_LINE_COLOR  = "#FFFFFF"  # 새로 그리는 사각형은 흰 테두리로 시작
DEFAULT_SHAPE_LINE_WIDTH = 2.0     # pt
DEFAULT_SHAPE_FILL_COLOR = "#FFFFFF"
DEFAULT_HIGHLIGHT_COLOR  = "#FFFF00"


# ══════════════════════════════════════════════════════════
#  공용 유틸
# ══════════════════════════════════════════════════════════
def _shade(hexcol, factor):
    """hexcol 을 factor 비율로 밝기 조정 (hover/pressed 색상 자동 계산용)"""
    h = hexcol.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r, g, b = (max(0, min(255, int(c*factor))) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def mkbtn(p, txt, cmd, bg=ACCENT, fg="white", px=12, py=8, **kw):
    if bg == ACCENT:
        hover, press = ACCENT_L, ACCENT_D
    else:
        hover, press = _shade(bg, 0.88), _shade(bg, 0.76)
    b  = tk.Button(p, text=txt, command=cmd, bg=bg, fg=fg,
                   font=FONT_B, relief="flat", cursor="hand2",
                   padx=px, pady=py, bd=0,
                   activebackground=press, activeforeground=fg, **kw)
    b.bind("<Enter>", lambda e: b.config(bg=hover))
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    return b


def parse_paths(data: str) -> list:
    out, i = [], 0
    data = data.strip()
    while i < len(data):
        if data[i] == "{":
            e = data.index("}", i); out.append(data[i+1:e]); i = e+2
        elif data[i] == " ":
            i += 1
        else:
            e = data.find(" ", i)
            if e == -1: out.append(data[i:]); break
            out.append(data[i:e]); i = e
    return out


def make_thumb(path, pidx, tw, th, factor=2.5):
    """factor: tw×th 기준 몇 배 해상도로 캐싱할지. 카드 확대(줌인) 시에도
    미리 캐싱해둔 이미지를 다시 늘려 흐려지지 않도록 여유 있게 렌더링한다."""
    if not PREVIEW_OK: return None
    try:
        doc  = fitz.open(path)
        if pidx >= len(doc): return None
        page = doc[pidx]
        sc   = min(tw/page.rect.width, th/page.rect.height) * factor
        pix  = page.get_pixmap(matrix=fitz.Matrix(sc, sc), alpha=False)
        img  = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img.thumbnail((int(tw*factor), int(th*factor)), Image.LANCZOS)
        doc.close()
        return img
    except Exception:
        return None


def sep_v(p, h=26):
    tk.Frame(p, bg=BORDER, width=1, height=h).pack(side="left", padx=8)

def sep_h(p):
    tk.Frame(p, bg=BORDER, height=1).pack(fill="x", pady=6)


def rr(canvas, x1, y1, x2, y2, r=12, tags=(), **kw):
    """캔버스에 둥근 모서리 사각형 그리기 (polygon smooth)"""
    r = max(0, min(r, (x2-x1)//2, (y2-y1)//2))
    pts = [
        x1+r, y1,  x2-r, y1,
        x2,   y1,  x2,   y1+r,
        x2,   y2-r,x2,   y2,
        x2-r, y2,  x1+r, y2,
        x1,   y2,  x1,   y2-r,
        x1,   y1+r,x1,   y1,
    ]
    return canvas.create_polygon(pts, smooth=True, tags=tags, **kw)


# ══════════════════════════════════════════════════════════
#  좌표 변환 (mm ↔ pt, 원본 페이지 pt ↔ 회전된 화면 픽셀)
#
#  현재 편집 좌표계는 PyMuPDF 렌더링/Canvas 와 쉽게 대응하기 위한
#  좌상단 원점 + Y 아래 방향의 "편집 좌표계"이다 ("PDF pt" 라고 부르지만
#  PDF 표준 좌표계와는 다르다는 점에 주의):
#    - 회전을 적용하기 전(원본) 페이지 기준, 좌측 상단이 원점
#    - X 는 오른쪽, Y 는 아래쪽으로 증가 (단위: pt, 1pt = 1/72 inch)
#    - 텍스트/도형의 위치는 이 좌표계로 annots 에 저장한다 (줌/팬/회전과 무관)
#
#  최종 PDF에 실제로 내용을 굽는 단계(Phase 4 이후)에서는 PyMuPDF/PDF의
#  실제 좌표계(좌하단 원점, Y 위쪽 증가)에 맞게 변환해야 한다:
#  pdf_native_y = page_h_pt - our_y
#  이 변환은 이번 Phase 에서는 구현하지 않는다.
# ══════════════════════════════════════════════════════════
MM_PER_INCH = 25.4
PT_PER_INCH = 72.0

def mm_to_pt(mm):
    return mm * PT_PER_INCH / MM_PER_INCH

def pt_to_mm(pt):
    return pt * MM_PER_INCH / PT_PER_INCH


def rotate_point_pt(x, y, w, h, rot):
    """원본(회전 전) 페이지 pt 좌표 (x,y) 를, 폭 w·높이 h 인 페이지를
    rot(0/90/180/270, 시계방향)만큼 회전했을 때의 pt 좌표로 변환한다."""
    rot = rot % 360
    if rot == 0:   return x, y
    if rot == 90:  return h - y, x
    if rot == 180: return w - x, h - y
    if rot == 270: return y, w - x
    raise ValueError(f"invalid rot {rot}")


def unrotate_point_pt(x, y, w, h, rot):
    """rotate_point_pt() 의 역변환. w,h 는 항상 원본(회전 전) 페이지 크기."""
    rot = rot % 360
    if rot == 0:   return x, y
    if rot == 90:  return y, h - x
    if rot == 180: return w - x, h - y
    if rot == 270: return w - y, x
    raise ValueError(f"invalid rot {rot}")


def rotated_size_pt(w, h, rot):
    """rot 만큼 회전했을 때의 (폭, 높이). 90/270 이면 폭·높이가 뒤바뀐다."""
    return (w, h) if rot % 180 == 0 else (h, w)


def pdf_to_screen(x, y, page_w_pt, page_h_pt, rot, scale, cx, cy):
    """원본 페이지 pt 좌표 → 캔버스 픽셀 좌표.
    scale: pt→px 배율, (cx,cy): 회전+확대된 페이지 이미지의 캔버스 중심 좌표."""
    rx, ry = rotate_point_pt(x, y, page_w_pt, page_h_pt, rot)
    rw, rh = rotated_size_pt(page_w_pt, page_h_pt, rot)
    px = cx - (rw*scale)/2 + rx*scale
    py = cy - (rh*scale)/2 + ry*scale
    return px, py


def screen_to_pdf(px, py, page_w_pt, page_h_pt, rot, scale, cx, cy):
    """pdf_to_screen() 의 역변환."""
    rw, rh = rotated_size_pt(page_w_pt, page_h_pt, rot)
    rx = (px - cx + (rw*scale)/2) / scale
    ry = (py - cy + (rh*scale)/2) / scale
    return unrotate_point_pt(rx, ry, page_w_pt, page_h_pt, rot)


# ══════════════════════════════════════════════════════════
#  텍스트 annot 을 실제 PDF 로 굽기 (내보내기 시점)
#
#  annot["x"]/["y"] 는 위 좌표계(원본 페이지 기준 좌상단 원점, Y 아래
#  증가) 로 저장되어 있다. PyMuPDF 의 insert_text() 좌표도 동일하게
#  "회전 적용 전 콘텐츠 스트림" 기준이므로, 소스 PDF 자체에 이미 걸려
#  있던 회전(native_rot)만 역변환해주면 그대로 삽입할 수 있다 — 우리
#  앱이 추가한 회전(pg["rot"])은 페이지 자체를 회전시키는 것이므로
#  텍스트를 따로 변환할 필요가 없다 (페이지 콘텐츠와 함께 회전됨).
# ══════════════════════════════════════════════════════════
def _color_hex_to_rgb01(hexcol):
    h = (hexcol or DEFAULT_ANNOT_COLOR).lstrip("#")
    try:
        return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))
    except Exception:
        return (0.0, 0.0, 0.0)


def _find_font_file(family, bold=False, italic=False):
    """Windows 레지스트리에서 폰트 패밀리 이름에 맞는 실제 폰트 파일
    경로를 찾는다. Windows 가 아니거나 찾지 못하면 None (호출부에서
    한글도 지원하는 PyMuPDF 내장 CJK 폰트로 대체)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
        reg = {}
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                base = name.replace("(TrueType)", "").replace("(OpenType)", "").strip()
                reg[base] = value

        def resolve(path):
            if not os.path.isabs(path):
                path = os.path.join(fonts_dir, path)
            return path if os.path.exists(path) else None

        suffixes = []
        if bold and italic: suffixes.append(" Bold Italic")
        if bold: suffixes.append(" Bold")
        if italic: suffixes.append(" Italic")
        suffixes.append("")
        for suf in suffixes:
            hit = reg.get(f"{family}{suf}")
            if hit:
                resolved = resolve(hit)
                if resolved: return resolved
        for base, path in reg.items():
            if base.startswith(family):
                resolved = resolve(path)
                if resolved: return resolved
    except Exception:
        pass
    return None


def _resolve_annot_font(family, bold, italic, alias):
    """(fitz.Font, fontfile 경로 또는 None, insert_text 에 넘길 fontname)
    을 반환한다. 실제 폰트 파일을 못 찾으면 한글을 포함해 폭넓게
    지원하는 PyMuPDF 내장 CJK 폴백 폰트("korea")로 대체하는데, 이 경우
    fontname 은 반드시 그 예약된 이름("korea") 그대로 써야 하므로 우리가
    붙인 별칭(alias) 대신 그 이름을 함께 돌려준다."""
    path = _find_font_file(family, bold, italic)
    try:
        if path:
            return fitz.Font(fontfile=path), path, alias
    except Exception:
        pass
    try:
        return fitz.Font(fontname="korea"), None, "korea"
    except Exception:
        return fitz.Font(fontname="helv"), None, "helv"


def _bake_text_annot(page, a, raw_w, raw_h, native_rot, font_cache):
    """annot 하나를 page(원본 회전 native_rot 을 아직 갖고 있는 상태)에
    실제 텍스트로 삽입한다. font_cache 는 (family,bold,italic) ->
    (fitz.Font, fontfile, insert_text 용 fontname) 을 캐싱해 같은 폰트를
    여러 번 등록하지 않게 한다."""
    x_pt, y_pt = a["x"], a["y"]
    if native_rot:
        x_pt, y_pt = unrotate_point_pt(x_pt, y_pt, raw_w, raw_h, native_rot)

    family = a.get("font", DEFAULT_ANNOT_FONT)
    bold = bool(a.get("bold"))
    italic = bool(a.get("italic"))
    cache_key = (family, bold, italic)
    if cache_key not in font_cache:
        font_cache[cache_key] = _resolve_annot_font(
            family, bold, italic, alias=f"F{len(font_cache)}")
    font, fontfile, fontname = font_cache[cache_key]

    size = a.get("font_size", DEFAULT_ANNOT_SIZE)
    color = _color_hex_to_rgb01(a.get("color", DEFAULT_ANNOT_COLOR))
    align = a.get("align", "left")
    lines = (a.get("text", "") or "").split("\n")
    try:
        ascent = size * (font.ascender or 0.8)
    except Exception:
        ascent = size * 0.8
    line_height = size * 1.2
    try:
        if fontfile:
            # 실제 폰트 파일을 그대로 삽입/측정 둘 다에 쓰므로 일치한다.
            widths = [font.text_length(ln, fontsize=size) for ln in lines]
        else:
            # "korea"/"helv" 같은 내장 이름은 fitz.Font(fontname=...) 객체로
            # 잰 길이가 insert_text(fontname=...) 가 실제로 그리는 폭과
            # 어긋날 수 있다(서로 다른 내부 리소스로 풀림) — 모듈 레벨
            # get_text_length() 는 insert_text 와 같은 방식으로 풀리므로
            # 그 쪽을 대신 쓴다.
            widths = [fitz.get_text_length(ln, fontname=fontname, fontsize=size) for ln in lines]
    except Exception:
        widths = [0.0 for _ in lines]

    # Tk canvas 의 angle(반시계+)과 통일하려고 부호를 반전했던 것과 동일한
    # 이유로, PyMuPDF Matrix.prerotate() 도 반시계+ 이므로 부호를 반전한다.
    rot = (-a.get("rotation", 0.0)) % 360
    anchor = fitz.Point(x_pt, y_pt)
    mat = fitz.Matrix(1, 1).prerotate(rot) if rot else None

    # 정렬은 X 좌표(x_pt)를 기준선으로 삼아, 각 줄이 그 선에 좌/가운데/
    # 우측 중 어느 쪽을 맞출지 정한다(줄마다 너비가 달라도 각자 독립적으로
    # 이 기준선에 맞춰짐 — Canvas 쪽 anchor+justify 조합과 동일한 결과).
    for i, (line, w) in enumerate(zip(lines, widths)):
        if align == "center": dx = -w / 2
        elif align == "right": dx = -w
        else: dx = 0.0
        px, py = x_pt + dx, y_pt + ascent + i * line_height
        kwargs = dict(fontsize=size, color=color, fontname=fontname)
        if fontfile:
            kwargs["fontfile"] = fontfile
        if mat is not None:
            kwargs["morph"] = (anchor, mat)
        try:
            page.insert_text(fitz.Point(px, py), line, **kwargs)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════
#  도형(사각형/화살표/강조) annot 공통 유틸
#
#  텍스트는 기준점이 하나(x,y)지만 도형은 두 점(x0,y0)-(x1,y1) 으로
#  경계상자를 나타낸다. 사각형/강조는 항상 x0<x1, y0<y1 로 정규화해
#  저장하지만, 화살표는 시작->끝 방향이 의미가 있으므로 정규화하지
#  않는다.
# ══════════════════════════════════════════════════════════
def _annot_ref_point(a):
    """드래그 이동 오프셋 계산에 쓸 기준점."""
    if a.get("type") == "text":
        return a["x"], a["y"]
    return a["x0"], a["y0"]


def _move_annot_to(a, ref_x, ref_y):
    """_annot_ref_point() 로 얻은 기준점을 새 위치로 옮긴다. 도형은
    폭/높이/방향을 그대로 유지한 채 통째로 평행이동한다."""
    if a.get("type") == "text":
        a["x"], a["y"] = ref_x, ref_y
    else:
        dx, dy = ref_x - a["x0"], ref_y - a["y0"]
        a["x0"] += dx; a["y0"] += dy
        a["x1"] += dx; a["y1"] += dy


def _draw_arrow_pdf(page, p0, p1, color, line_width):
    """PyMuPDF 페이지에 화살표(직선 + 삼각형 화살촉)를 그린다."""
    page.draw_line(p0, p1, color=color, width=line_width)
    dx, dy = p1.x - p0.x, p1.y - p0.y
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return
    ux, uy = dx / length, dy / length
    head_len = max(8.0, line_width * 4)
    head_w   = max(5.0, line_width * 2.5)
    bx, by = p1.x - ux * head_len, p1.y - uy * head_len
    px, py = -uy, ux   # 진행방향에 수직인 단위벡터
    left  = fitz.Point(bx + px * head_w, by + py * head_w)
    right = fitz.Point(bx - px * head_w, by - py * head_w)
    page.draw_polyline([p1, left, right], color=color, fill=color,
                        width=0, closePath=True)


def _bake_shape_annot(page, a, raw_w, raw_h, native_rot):
    """사각형/화살표/강조 annot 하나를 실제 PDF 콘텐츠로 굽는다."""
    x0, y0, x1, y1 = a["x0"], a["y0"], a["x1"], a["y1"]
    if native_rot:
        x0, y0 = unrotate_point_pt(x0, y0, raw_w, raw_h, native_rot)
        x1, y1 = unrotate_point_pt(x1, y1, raw_w, raw_h, native_rot)

    t = a.get("type")
    try:
        if t == "rect":
            rect = fitz.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            fill = (_color_hex_to_rgb01(a.get("fill_color", DEFAULT_SHAPE_FILL_COLOR))
                    if a.get("fill_enabled") else None)
            page.draw_rect(rect,
                color=_color_hex_to_rgb01(a.get("line_color", DEFAULT_SHAPE_LINE_COLOR)),
                fill=fill, width=a.get("line_width", DEFAULT_SHAPE_LINE_WIDTH))
        elif t == "arrow":
            _draw_arrow_pdf(page, fitz.Point(x0, y0), fitz.Point(x1, y1),
                _color_hex_to_rgb01(a.get("line_color", DEFAULT_SHAPE_LINE_COLOR)),
                a.get("line_width", DEFAULT_SHAPE_LINE_WIDTH))
        elif t == "highlight":
            rect = fitz.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            hl = page.add_highlight_annot(rect)
            hl.set_colors(stroke=_color_hex_to_rgb01(a.get("fill_color", DEFAULT_HIGHLIGHT_COLOR)))
            hl.update()
    except Exception:
        pass


def _bake_all_annots(page, pg, native_rot, font_cache):
    """pg 의 모든 텍스트/도형 annot 을 page 에 굽는다. 내보내기와 정리
    탭 카드 썸네일 미리보기가 같은 로직을 공유해, 미리보기에서 본 것과
    실제 저장 결과가 어긋나지 않게 한다."""
    annots = pg.get("annots", [])
    if not annots: return
    raw_w, raw_h = rotated_size_pt(pg.get("page_w_pt") or 0, pg.get("page_h_pt") or 0, native_rot)
    for a in annots:
        if a.get("type") == "text":
            _bake_text_annot(page, a, raw_w, raw_h, native_rot, font_cache)
        elif a.get("type") in ("rect", "arrow", "highlight"):
            _bake_shape_annot(page, a, raw_w, raw_h, native_rot)


def make_thumb_for_page(pg, tw, th, factor=2.5):
    """카드 썸네일을 텍스트/도형 annot 까지 반영해서 만든다 — 내보내기와
    동일한 굽기 로직(_bake_all_annots)을 재사용해서 정리 탭 미리보기와
    실제 저장 결과가 어긋나지 않게 한다. 우리 앱이 추가한 회전(pg["rot"])
    은 이 "회전 전" 기준 이미지에는 반영하지 않는다 — 기존 관례대로
    화면에 표시할 때마다 별도로 PIL 회전을 적용한다
    (OrganizeTab._render/_draw_ghost 참고)."""
    if not PREVIEW_OK: return None
    try:
        src_doc = fitz.open(pg["src"])
        pidx = pg["pidx"]
        if pidx >= len(src_doc):
            src_doc.close(); return None
        native_rot = src_doc[pidx].rotation

        tmp_doc = fitz.open()
        tmp_doc.insert_pdf(src_doc, from_page=pidx, to_page=pidx)
        page = tmp_doc[0]
        src_doc.close()

        _bake_all_annots(page, pg, native_rot, {})

        sc  = min(tw/page.rect.width, th/page.rect.height) * factor
        pix = page.get_pixmap(matrix=fitz.Matrix(sc, sc), alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img.thumbnail((int(tw*factor), int(th*factor)), Image.LANCZOS)
        tmp_doc.close()
        return img
    except Exception:
        return None


# ══════════════════════════════════════════════════════════
#  텍스트 속성 패널 (PreviewWin 우측에 붙는다, 선택 시에만 표시)
# ══════════════════════════════════════════════════════════
class TextPropPanel(tk.Frame):
    def __init__(self, master, owner):
        super().__init__(master, bg=PANEL, width=230)
        self.owner = owner          # PreviewWin 인스턴스 (변경 통지용)
        self.annot = None
        self.page_h_pt = None       # Y 표시를 좌하단 원점으로 뒤집는 데 필요
        self.pack_propagate(False)  # 내용과 무관하게 폭 고정
        self._build()

    def _build(self):
        pad = dict(padx=14)
        tk.Label(self, text="텍스트 속성", font=FONT_B, bg=PANEL, fg=TEXT)\
            .pack(anchor="w", padx=14, pady=(12,4))
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=14, pady=(0,8))

        # ── 내용 ──────────────────────────────────────────
        tk.Label(self, text="내용", font=FONT_S, bg=PANEL, fg=TEXT_DIM).pack(anchor="w", **pad)
        self.text_var = tk.StringVar()
        self.content_entry = tk.Entry(self, textvariable=self.text_var, font=FONT, bg="white", fg=TEXT)
        self.content_entry.pack(fill="x", padx=14, pady=(2,8))
        self.content_entry.bind("<Return>", lambda e: self._apply_text())
        self.content_entry.bind("<FocusOut>", lambda e: self._apply_text())

        # ── 위치 (X/Y, mm) ───────────────────────────────
        tk.Label(self, text="위치 (기준: 페이지 좌측 하단)", font=FONT_S,
                 bg=PANEL, fg=TEXT_DIM).pack(anchor="w", padx=14, pady=(4,2))
        tk.Label(self, text="↑↓ 또는 휠로 미세조정 (Shift=1mm)", font=FONT_XS,
                 bg=PANEL, fg=TEXT_DIM).pack(anchor="w", padx=14)

        xrow = tk.Frame(self, bg=PANEL); xrow.pack(fill="x", padx=14, pady=(2,0))
        tk.Label(xrow, text="X", font=FONT_S, bg=PANEL, fg=TEXT, width=2).pack(side="left")
        self.x_var = tk.StringVar()
        e_x = tk.Entry(xrow, textvariable=self.x_var, font=FONT, width=9, bg="white", fg=TEXT)
        e_x.pack(side="left")
        tk.Label(xrow, text="mm", font=FONT_XS, bg=PANEL, fg=TEXT_DIM).pack(side="left", padx=(4,0))
        e_x.bind("<Return>", lambda e: self._apply_xy())
        e_x.bind("<FocusOut>", lambda e: self._apply_xy())
        e_x.bind("<Up>",          lambda e: self._nudge_x(0.1))
        e_x.bind("<Down>",        lambda e: self._nudge_x(-0.1))
        e_x.bind("<Shift-Up>",    lambda e: self._nudge_x(1.0))
        e_x.bind("<Shift-Down>",  lambda e: self._nudge_x(-1.0))
        e_x.bind("<MouseWheel>",  lambda e: self._nudge_x(0.1 if e.delta > 0 else -0.1))

        yrow = tk.Frame(self, bg=PANEL); yrow.pack(fill="x", padx=14, pady=(4,4))
        tk.Label(yrow, text="Y", font=FONT_S, bg=PANEL, fg=TEXT, width=2).pack(side="left")
        self.y_var = tk.StringVar()
        e_y = tk.Entry(yrow, textvariable=self.y_var, font=FONT, width=9, bg="white", fg=TEXT)
        e_y.pack(side="left")
        tk.Label(yrow, text="mm", font=FONT_XS, bg=PANEL, fg=TEXT_DIM).pack(side="left", padx=(4,0))
        e_y.bind("<Return>", lambda e: self._apply_xy())
        e_y.bind("<FocusOut>", lambda e: self._apply_xy())
        e_y.bind("<Up>",          lambda e: self._nudge_y(0.1))
        e_y.bind("<Down>",        lambda e: self._nudge_y(-0.1))
        e_y.bind("<Shift-Up>",    lambda e: self._nudge_y(1.0))
        e_y.bind("<Shift-Down>",  lambda e: self._nudge_y(-1.0))
        e_y.bind("<MouseWheel>",  lambda e: self._nudge_y(0.1 if e.delta > 0 else -0.1))

        self.page_size_lbl = tk.Label(self, text="", font=FONT_XS, bg=PANEL, fg=TEXT_DIM)
        self.page_size_lbl.pack(anchor="w", padx=14, pady=(2,8))

        # ── 글꼴 ──────────────────────────────────────────
        tk.Label(self, text="글꼴", font=FONT_S, bg=PANEL, fg=TEXT_DIM).pack(anchor="w", **pad)
        self.font_var = tk.StringVar()
        self.font_combo = ttk.Combobox(self, textvariable=self.font_var, values=self._font_list(),
                                        state="readonly", font=FONT_S)
        self.font_combo.pack(fill="x", padx=14, pady=(2,8))
        self.font_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_font())

        # ── 크기 (- [숫자입력] + 스테퍼) ─────────────────────
        tk.Label(self, text="크기 (pt)", font=FONT_S, bg=PANEL, fg=TEXT_DIM).pack(anchor="w", **pad)
        size_row = tk.Frame(self, bg=PANEL); size_row.pack(fill="x", padx=14, pady=(2,8))
        self.SIZE_STEP = 5
        self.size_minus_btn = tk.Button(size_row, text="−", command=lambda: self._step_size(-self.SIZE_STEP),
                  bg=TOOLBAR, fg=TEXT, font=FONT_B, relief="flat", bd=0, width=2,
                  cursor="hand2", activebackground=_shade(TOOLBAR, 0.9))
        self.size_minus_btn.pack(side="left")
        self.size_var = tk.StringVar()
        e_size = tk.Entry(size_row, textvariable=self.size_var, font=FONT, width=5,
                           bg="white", fg=TEXT, justify="center")
        e_size.pack(side="left", padx=4)
        self.size_plus_btn = tk.Button(size_row, text="+", command=lambda: self._step_size(self.SIZE_STEP),
                  bg=TOOLBAR, fg=TEXT, font=FONT_B, relief="flat", bd=0, width=2,
                  cursor="hand2", activebackground=_shade(TOOLBAR, 0.9))
        self.size_plus_btn.pack(side="left")
        e_size.bind("<Return>", lambda e: self._apply_size())
        e_size.bind("<FocusOut>", lambda e: self._apply_size())

        # ── 색상 ──────────────────────────────────────────
        crow = tk.Frame(self, bg=PANEL); crow.pack(fill="x", padx=14, pady=(0,8))
        tk.Label(crow, text="색상", font=FONT_S, bg=PANEL, fg=TEXT_DIM).pack(side="left")
        # 색이 흰색 등 패널 배경과 비슷할 때도 클릭 가능한 버튼임을 알 수
        # 있도록, 살짝 다른 색(TOOLBAR)의 칩 안에 스와치를 넣는다.
        color_chip = tk.Frame(crow, bg=TOOLBAR, padx=3, pady=3)
        color_chip.pack(side="left", padx=8)
        self.color_btn = tk.Button(color_chip, text="   ", bg=DEFAULT_ANNOT_COLOR, width=4,
                                    relief="flat", bd=0, cursor="hand2", command=self._pick_color)
        self.color_btn.pack()

        # ── 굵게 / 기울임 ─────────────────────────────────
        birow = tk.Frame(self, bg=PANEL); birow.pack(fill="x", padx=10, pady=(0,8))
        self.bold_var = tk.BooleanVar()
        self.italic_var = tk.BooleanVar()
        tk.Checkbutton(birow, text="굵게", variable=self.bold_var, command=self._apply_style,
                       bg=PANEL, fg=TEXT, selectcolor=ACCENT,
                       activebackground=PANEL, font=FONT_S, bd=0,
                       highlightthickness=0).pack(side="left", padx=4)
        tk.Checkbutton(birow, text="기울임", variable=self.italic_var, command=self._apply_style,
                       bg=PANEL, fg=TEXT, selectcolor=ACCENT,
                       activebackground=PANEL, font=FONT_S, bd=0,
                       highlightthickness=0).pack(side="left", padx=4)

        # ── 정렬 (좌/가운데/우측 아이콘 버튼) ────────────────
        tk.Label(self, text="정렬", font=FONT_S, bg=PANEL, fg=TEXT_DIM).pack(anchor="w", **pad)
        align_row = tk.Frame(self, bg=PANEL); align_row.pack(fill="x", padx=14, pady=(2,8))
        self.align_btns = {}
        for key in ("left", "center", "right"):
            btn = self._make_align_icon(align_row, key)
            btn.pack(side="left", padx=(0,6))
            self.align_btns[key] = btn

        # ── 회전 (텍스트 자체 회전 — 페이지 회전과 별개) ──
        tk.Label(self, text="회전 (°)", font=FONT_S, bg=PANEL, fg=TEXT_DIM).pack(anchor="w", **pad)
        self.rot_var = tk.StringVar()
        e_rot = tk.Entry(self, textvariable=self.rot_var, font=FONT, width=9, bg="white", fg=TEXT)
        e_rot.pack(anchor="w", padx=14, pady=(2,8))
        e_rot.bind("<Return>", lambda e: self._apply_rotation())
        e_rot.bind("<FocusOut>", lambda e: self._apply_rotation())

        # ── 삭제 ──────────────────────────────────────────
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=14, pady=(4,10))
        tk.Button(self, text="🗑 이 텍스트 삭제", command=self._delete_annot,
                  bg=DANGER, fg="white", font=FONT, relief="flat",
                  padx=12, pady=7, cursor="hand2", bd=0,
                  activebackground=_shade(DANGER, 0.9)).pack(fill="x", padx=14, pady=(0,14))

    def _delete_annot(self):
        if self.annot is None: return
        self.owner._delete_selected_annot()

    def _font_list(self):
        try:
            from tkinter import font as tkfont
            names = sorted(set(tkfont.families(self)))
            return names if names else [DEFAULT_ANNOT_FONT]
        except Exception:
            return [DEFAULT_ANNOT_FONT]

    # ── 정렬 아이콘 버튼 ──────────────────────────────────
    def _make_align_icon(self, parent, align_key):
        """좌/가운데/우측 정렬 아이콘(막대 3개)을 캔버스에 직접 그려서
        만든 버튼. 클릭하면 그 정렬로 바꾸고, 현재 선택된 정렬은 배경을
        강조색으로 표시한다."""
        c = tk.Canvas(parent, width=40, height=26, bg=TOOLBAR, highlightthickness=0, cursor="hand2")
        bar_w, bar_h, gap, x_pad, y0 = 24, 3, 5, 8, 6
        widths = (bar_w, bar_w * 0.65, bar_w * 0.85)
        for i, w in enumerate(widths):
            y = y0 + i * (bar_h + gap)
            if align_key == "left":
                x0 = x_pad
            elif align_key == "center":
                x0 = x_pad + (bar_w - w) / 2
            else:
                x0 = x_pad + (bar_w - w)
            c.create_rectangle(x0, y, x0 + w, y + bar_h, fill=TEXT_DIM, outline="", tags="bar")
        c.bind("<Button-1>", lambda e, k=align_key: self._set_align(k))
        return c

    def _set_align(self, key):
        if self.annot is None: return
        if self.annot.get("align", "left") == key: return
        self.owner._push_undo()
        self.annot["align"] = key
        self._refresh_align_buttons()
        self.owner._on_annot_prop_changed()

    def _refresh_align_buttons(self):
        cur = self.annot.get("align", "left") if self.annot else "left"
        for key, btn in self.align_btns.items():
            active = (key == cur)
            btn.config(bg=ACCENT if active else TOOLBAR)
            fill = "white" if active else TEXT_DIM
            for item in btn.find_withtag("bar"):
                btn.itemconfig(item, fill=fill)

    # ── 크기 스테퍼(-/+) ──────────────────────────────────
    def _step_size(self, delta):
        if self.annot is None: return
        try:
            v = float(self.size_var.get())
        except ValueError:
            v = self.annot.get("font_size", DEFAULT_ANNOT_SIZE)
        v = max(1.0, v + delta)
        self.size_var.set(f"{v:.2f}")
        self._apply_size()

    # ── annot 표시 ────────────────────────────────────────
    def show_annot(self, annot, page_w_pt, page_h_pt):
        self.annot = annot
        self.page_h_pt = page_h_pt
        if annot is None:
            return
        self.text_var.set(annot.get("text", ""))
        self.x_var.set(f"{pt_to_mm(annot['x']):.2f}")
        self.y_var.set(f"{self._y_pt_to_disp_mm(annot['y']):.2f}")
        font_name = annot.get("font", DEFAULT_ANNOT_FONT)
        self.font_var.set(font_name if font_name in self.font_combo["values"] else DEFAULT_ANNOT_FONT)
        self.size_var.set(f"{annot.get('font_size', DEFAULT_ANNOT_SIZE):.2f}")
        self.bold_var.set(bool(annot.get("bold", False)))
        self.italic_var.set(bool(annot.get("italic", False)))
        self._refresh_align_buttons()
        self.rot_var.set(f"{annot.get('rotation', 0.0):.1f}")
        color = annot.get("color", DEFAULT_ANNOT_COLOR)
        try: self.color_btn.config(bg=color)
        except Exception: pass
        if page_w_pt and page_h_pt:
            self.page_size_lbl.config(
                text=f"페이지 크기: {pt_to_mm(page_w_pt):.2f} × {pt_to_mm(page_h_pt):.2f} mm")
        else:
            self.page_size_lbl.config(text="")

    def refresh_xy_only(self):
        """드래그 등으로 좌표만 바뀌었을 때, 입력 포커스를 방해하지 않고
        X/Y 표시만 갱신한다 (양방향 동기화, 8번 요구사항)."""
        if self.annot is None: return
        self.x_var.set(f"{pt_to_mm(self.annot['x']):.2f}")
        self.y_var.set(f"{self._y_pt_to_disp_mm(self.annot['y']):.2f}")

    # ── Y 좌표 표시 변환 ────────────────────────────────────
    # 내부 저장(annot["y"])은 렌더링/회전 계산과 맞추기 위해 좌상단 원점 +
    # Y 아래로 증가하는 편집 좌표계를 그대로 쓰지만, 화면에 보여주는 X/Y
    # 입력창은 사용자에게 익숙한 PDF 표준 관례(좌하단 원점, Y 위로 증가)로
    # 표시한다. 페이지 높이를 기준으로 뒤집기만 하면 되고, X 는 두 좌표계에서
    # 동일하므로 변환이 필요 없다.
    def _y_pt_to_disp_mm(self, y_pt):
        if self.page_h_pt:
            return pt_to_mm(self.page_h_pt) - pt_to_mm(y_pt)
        return pt_to_mm(y_pt)

    def _disp_mm_to_y_pt(self, y_disp_mm):
        if self.page_h_pt:
            return mm_to_pt(pt_to_mm(self.page_h_pt) - y_disp_mm)
        return mm_to_pt(y_disp_mm)

    def focus_content_for_edit(self):
        """새 텍스트 생성 직후 '내용' 입력창에 포커스를 옮기고 전체 선택해서
        곧바로 타이핑으로 덮어쓸 수 있게 한다 (팝업 대화상자 없이 생성)."""
        self.content_entry.focus_set()
        self.content_entry.selection_range(0, tk.END)

    # ── X/Y 미세조정 (방향키 · 마우스 휠) ─────────────────────
    def _nudge_x(self, delta_mm):
        if self.annot is None: return "break"
        try: v = float(self.x_var.get())
        except ValueError: return "break"
        self.x_var.set(f"{v + delta_mm:.2f}")
        self._apply_xy()
        return "break"

    def _nudge_y(self, delta_mm):
        if self.annot is None: return "break"
        try: v = float(self.y_var.get())
        except ValueError: return "break"
        self.y_var.set(f"{v + delta_mm:.2f}")
        self._apply_xy()
        return "break"

    # ── 각 필드 적용 (Enter / 포커스 아웃 시점에 반영) ───────
    # 아래 _apply_*/_pick_* 들은 실제 값이 바뀔 때만 owner._push_undo() 로
    # 실행취소 스냅샷을 남긴다 — Enter 로 확정한 뒤 포커스가 빠져나가면서
    # <FocusOut> 이 같은 값으로 한 번 더 호출되는 등, 값이 그대로인 중복
    # 호출에서 실행취소 스택에 빈 항목이 쌓이지 않도록 하기 위함이다.
    def _apply_text(self):
        if self.annot is None: return
        new_text = self.text_var.get()
        if new_text == self.annot.get("text", ""): return
        self.owner._push_undo()
        self.annot["text"] = new_text
        self.owner._on_annot_prop_changed()

    def _apply_xy(self):
        if self.annot is None: return
        try:
            x_mm = float(self.x_var.get())
            y_mm = float(self.y_var.get())
        except ValueError:
            messagebox.showwarning("잘못된 값", "X/Y 는 숫자(mm)로 입력해주세요.", parent=self)
            self.refresh_xy_only()
            return
        # 내부 저장은 항상 pt, 정밀도를 그대로 유지한다 (화면 표시만 반올림).
        # Y 는 입력창에 좌하단 원점 기준으로 표시되므로 내부 좌표로 되돌린다.
        new_x = mm_to_pt(x_mm)
        new_y = self._disp_mm_to_y_pt(y_mm)
        if new_x == self.annot["x"] and new_y == self.annot["y"]:
            return
        self.owner._push_undo()
        self.annot["x"] = new_x
        self.annot["y"] = new_y
        self.refresh_xy_only()
        self.owner._on_annot_prop_changed()

    def _apply_size(self):
        if self.annot is None: return
        try:
            size = float(self.size_var.get())
            if size <= 0: raise ValueError
        except ValueError:
            messagebox.showwarning("잘못된 값", "크기는 0보다 큰 숫자(pt)로 입력해주세요.", parent=self)
            self.size_var.set(f"{self.annot.get('font_size', DEFAULT_ANNOT_SIZE):.2f}")
            return
        if size == self.annot.get("font_size", DEFAULT_ANNOT_SIZE):
            self.size_var.set(f"{size:.2f}")
            return
        self.owner._push_undo()
        self.annot["font_size"] = size
        self.size_var.set(f"{size:.2f}")
        self.owner._on_annot_prop_changed()

    def _apply_rotation(self):
        if self.annot is None: return
        try:
            rot = float(self.rot_var.get())
        except ValueError:
            messagebox.showwarning("잘못된 값", "회전 값은 숫자(도)로 입력해주세요.", parent=self)
            self.rot_var.set(f"{self.annot.get('rotation', 0.0):.1f}")
            return
        rot = rot % 360
        if rot == self.annot.get("rotation", 0.0):
            self.rot_var.set(f"{rot:.1f}")
            return
        self.owner._push_undo()
        self.annot["rotation"] = rot
        self.rot_var.set(f"{rot:.1f}")
        self.owner._on_annot_prop_changed()

    def _apply_font(self):
        if self.annot is None: return
        new_font = self.font_var.get() or DEFAULT_ANNOT_FONT
        if new_font == self.annot.get("font", DEFAULT_ANNOT_FONT): return
        self.owner._push_undo()
        self.annot["font"] = new_font
        self.owner._on_annot_prop_changed()

    def _apply_style(self):
        if self.annot is None: return
        new_bold = bool(self.bold_var.get())
        new_italic = bool(self.italic_var.get())
        if (new_bold == bool(self.annot.get("bold", False))
                and new_italic == bool(self.annot.get("italic", False))):
            return
        self.owner._push_undo()
        self.annot["bold"] = new_bold
        self.annot["italic"] = new_italic
        self.owner._on_annot_prop_changed()

    def _pick_color(self):
        if self.annot is None: return
        from tkinter import colorchooser
        cur = self.annot.get("color", DEFAULT_ANNOT_COLOR)
        _, hexcol = colorchooser.askcolor(color=cur, parent=self, title="텍스트 색상 선택")
        if hexcol and hexcol != cur:
            self.owner._push_undo()
            self.annot["color"] = hexcol
            self.color_btn.config(bg=hexcol)
            self.owner._on_annot_prop_changed()


# ══════════════════════════════════════════════════════════
#  도형(사각형/화살표/강조) 속성 패널
# ══════════════════════════════════════════════════════════
class ShapePropPanel(tk.Frame):
    def __init__(self, master, owner):
        super().__init__(master, bg=PANEL, width=230)
        self.owner = owner
        self.annot = None
        self.page_h_pt = None
        self.pack_propagate(False)
        self._build()

    def _build(self):
        pad = dict(padx=14)
        self.title_lbl = tk.Label(self, text="도형 속성", font=FONT_B, bg=PANEL, fg=TEXT)
        self.title_lbl.pack(anchor="w", padx=14, pady=(12,4))
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=14, pady=(0,8))

        # ── 위치/크기 (X0/Y0/X1/Y1, mm) ────────────────────
        tk.Label(self, text="위치/크기 (기준: 페이지 좌측 하단)", font=FONT_S,
                 bg=PANEL, fg=TEXT_DIM).pack(anchor="w", padx=14, pady=(4,2))

        def mkrow(label):
            row = tk.Frame(self, bg=PANEL); row.pack(fill="x", padx=14, pady=(2,0))
            tk.Label(row, text=label, font=FONT_S, bg=PANEL, fg=TEXT, width=2).pack(side="left")
            var = tk.StringVar()
            e = tk.Entry(row, textvariable=var, font=FONT, width=9, bg="white", fg=TEXT)
            e.pack(side="left")
            tk.Label(row, text="mm", font=FONT_XS, bg=PANEL, fg=TEXT_DIM).pack(side="left", padx=(4,0))
            e.bind("<Return>",   lambda ev: self._apply_geom())
            e.bind("<FocusOut>", lambda ev: self._apply_geom())
            return var

        self.x0_var = mkrow("X0")
        self.y0_var = mkrow("Y0")
        self.x1_var = mkrow("X1")
        self.y1_var = mkrow("Y1")

        self.page_size_lbl = tk.Label(self, text="", font=FONT_XS, bg=PANEL, fg=TEXT_DIM)
        self.page_size_lbl.pack(anchor="w", padx=14, pady=(2,8))

        # ── 선 색상/굵기 (사각형/화살표) ────────────────────
        self.line_frame = tk.Frame(self, bg=PANEL)
        tk.Label(self.line_frame, text="선", font=FONT_S, bg=PANEL, fg=TEXT_DIM)\
            .pack(anchor="w", padx=14)
        lrow = tk.Frame(self.line_frame, bg=PANEL); lrow.pack(fill="x", padx=14, pady=(2,8))
        # 선 색이 흰색 등 패널 배경과 비슷할 때도 클릭 가능한 버튼임을 알
        # 수 있도록, 살짝 다른 색(TOOLBAR)의 칩 안에 스와치를 넣는다.
        line_chip = tk.Frame(lrow, bg=TOOLBAR, padx=3, pady=3)
        line_chip.pack(side="left")
        self.line_color_btn = tk.Button(line_chip, text="   ", bg=DEFAULT_SHAPE_LINE_COLOR, width=4,
                                         relief="flat", bd=0, cursor="hand2", command=self._pick_line_color)
        self.line_color_btn.pack()
        self.line_width_var = tk.StringVar()
        e_lw = tk.Entry(lrow, textvariable=self.line_width_var, font=FONT, width=5, bg="white", fg=TEXT)
        e_lw.pack(side="left", padx=(8,2))
        tk.Label(lrow, text="pt 굵기", font=FONT_XS, bg=PANEL, fg=TEXT_DIM).pack(side="left")
        e_lw.bind("<Return>",   lambda e: self._apply_line_width())
        e_lw.bind("<FocusOut>", lambda e: self._apply_line_width())

        # ── 채움 (사각형 전용) ──────────────────────────────
        self.fill_frame = tk.Frame(self, bg=PANEL)
        frow = tk.Frame(self.fill_frame, bg=PANEL); frow.pack(fill="x", padx=10, pady=(0,8))
        self.fill_enabled_var = tk.BooleanVar()
        tk.Checkbutton(frow, text="채움", variable=self.fill_enabled_var, command=self._apply_fill_enabled,
                       bg=PANEL, fg=TEXT, selectcolor=ACCENT, activebackground=PANEL,
                       font=FONT_S, bd=0, highlightthickness=0).pack(side="left", padx=4)
        fill_chip = tk.Frame(frow, bg=TOOLBAR, padx=3, pady=3)
        fill_chip.pack(side="left", padx=8)
        self.fill_color_btn = tk.Button(fill_chip, text="   ", bg=DEFAULT_SHAPE_FILL_COLOR, width=4,
                                         relief="flat", bd=0, cursor="hand2", command=self._pick_fill_color)
        self.fill_color_btn.pack()

        # ── 강조 색상 (강조 전용) ───────────────────────────
        self.highlight_frame = tk.Frame(self, bg=PANEL)
        hrow = tk.Frame(self.highlight_frame, bg=PANEL); hrow.pack(fill="x", padx=14, pady=(0,8))
        tk.Label(hrow, text="강조 색상", font=FONT_S, bg=PANEL, fg=TEXT_DIM).pack(side="left")
        highlight_chip = tk.Frame(hrow, bg=TOOLBAR, padx=3, pady=3)
        highlight_chip.pack(side="left", padx=8)
        self.highlight_color_btn = tk.Button(highlight_chip, text="   ", bg=DEFAULT_HIGHLIGHT_COLOR, width=4,
                                              relief="flat", bd=0, cursor="hand2", command=self._pick_highlight_color)
        self.highlight_color_btn.pack()

        # ── 삭제 ────────────────────────────────────────────
        self._delete_sep = tk.Frame(self, bg=BORDER, height=1)
        self._delete_sep.pack(fill="x", padx=14, pady=(4,10))
        tk.Button(self, text="🗑 이 도형 삭제", command=self._delete_shape,
                  bg=DANGER, fg="white", font=FONT, relief="flat",
                  padx=12, pady=7, cursor="hand2", bd=0,
                  activebackground=_shade(DANGER, 0.9)).pack(fill="x", padx=14, pady=(0,14))

    # ── annot 표시 ────────────────────────────────────────
    def show_annot(self, annot, page_w_pt, page_h_pt):
        self.annot = annot
        self.page_h_pt = page_h_pt
        if annot is None:
            return
        t = annot.get("type")
        self.title_lbl.config(text={
            "rect": "사각형 속성", "arrow": "화살표 속성", "highlight": "강조 속성",
        }.get(t, "도형 속성"))
        self.refresh_xy_only()

        self.line_frame.pack_forget()
        self.fill_frame.pack_forget()
        self.highlight_frame.pack_forget()
        if t in ("rect", "arrow"):
            self.line_color_btn.config(bg=annot.get("line_color", DEFAULT_SHAPE_LINE_COLOR))
            self.line_width_var.set(f"{annot.get('line_width', DEFAULT_SHAPE_LINE_WIDTH):.1f}")
            self.line_frame.pack(fill="x", before=self._delete_sep)
        if t == "rect":
            self.fill_enabled_var.set(bool(annot.get("fill_enabled", False)))
            self.fill_color_btn.config(bg=annot.get("fill_color", DEFAULT_SHAPE_FILL_COLOR))
            self.fill_frame.pack(fill="x", before=self._delete_sep)
        if t == "highlight":
            self.highlight_color_btn.config(bg=annot.get("fill_color", DEFAULT_HIGHLIGHT_COLOR))
            self.highlight_frame.pack(fill="x", before=self._delete_sep)

        if page_w_pt and page_h_pt:
            self.page_size_lbl.config(
                text=f"페이지 크기: {pt_to_mm(page_w_pt):.2f} × {pt_to_mm(page_h_pt):.2f} mm")
        else:
            self.page_size_lbl.config(text="")

    def refresh_xy_only(self):
        if self.annot is None: return
        self.x0_var.set(f"{pt_to_mm(self.annot['x0']):.2f}")
        self.x1_var.set(f"{pt_to_mm(self.annot['x1']):.2f}")
        self.y0_var.set(f"{self._y_pt_to_disp_mm(self.annot['y0']):.2f}")
        self.y1_var.set(f"{self._y_pt_to_disp_mm(self.annot['y1']):.2f}")

    # 텍스트 속성 패널(TextPropPanel)과 동일한 좌하단 원점 표시 변환
    def _y_pt_to_disp_mm(self, y_pt):
        if self.page_h_pt:
            return pt_to_mm(self.page_h_pt) - pt_to_mm(y_pt)
        return pt_to_mm(y_pt)

    def _disp_mm_to_y_pt(self, y_disp_mm):
        if self.page_h_pt:
            return mm_to_pt(pt_to_mm(self.page_h_pt) - y_disp_mm)
        return mm_to_pt(y_disp_mm)

    def _apply_geom(self):
        if self.annot is None: return
        try:
            x0 = mm_to_pt(float(self.x0_var.get()))
            x1 = mm_to_pt(float(self.x1_var.get()))
            y0 = self._disp_mm_to_y_pt(float(self.y0_var.get()))
            y1 = self._disp_mm_to_y_pt(float(self.y1_var.get()))
        except ValueError:
            messagebox.showwarning("잘못된 값", "X0/Y0/X1/Y1 은 숫자(mm)로 입력해주세요.", parent=self)
            self.refresh_xy_only()
            return
        if (x0 == self.annot["x0"] and x1 == self.annot["x1"]
                and y0 == self.annot["y0"] and y1 == self.annot["y1"]):
            return
        self.owner._push_undo()
        self.annot["x0"], self.annot["x1"] = x0, x1
        self.annot["y0"], self.annot["y1"] = y0, y1
        self.refresh_xy_only()
        self.owner._on_annot_prop_changed()

    def _apply_line_width(self):
        if self.annot is None: return
        try:
            w = float(self.line_width_var.get())
            if w <= 0: raise ValueError
        except ValueError:
            messagebox.showwarning("잘못된 값", "굵기는 0보다 큰 숫자(pt)로 입력해주세요.", parent=self)
            self.line_width_var.set(f"{self.annot.get('line_width', DEFAULT_SHAPE_LINE_WIDTH):.1f}")
            return
        if w == self.annot.get("line_width", DEFAULT_SHAPE_LINE_WIDTH): return
        self.owner._push_undo()
        self.annot["line_width"] = w
        self.owner._on_annot_prop_changed()

    def _apply_fill_enabled(self):
        if self.annot is None: return
        new_val = bool(self.fill_enabled_var.get())
        if new_val == bool(self.annot.get("fill_enabled", False)): return
        self.owner._push_undo()
        self.annot["fill_enabled"] = new_val
        self.owner._on_annot_prop_changed()

    def _pick_line_color(self):
        if self.annot is None: return
        from tkinter import colorchooser
        cur = self.annot.get("line_color", DEFAULT_SHAPE_LINE_COLOR)
        _, hexcol = colorchooser.askcolor(color=cur, parent=self, title="선 색상 선택")
        if hexcol and hexcol != cur:
            self.owner._push_undo()
            self.annot["line_color"] = hexcol
            self.line_color_btn.config(bg=hexcol)
            self.owner._on_annot_prop_changed()

    def _pick_fill_color(self):
        if self.annot is None: return
        from tkinter import colorchooser
        cur = self.annot.get("fill_color", DEFAULT_SHAPE_FILL_COLOR)
        _, hexcol = colorchooser.askcolor(color=cur, parent=self, title="채움 색상 선택")
        if hexcol and hexcol != cur:
            self.owner._push_undo()
            self.annot["fill_color"] = hexcol
            self.fill_color_btn.config(bg=hexcol)
            self.owner._on_annot_prop_changed()

    def _pick_highlight_color(self):
        if self.annot is None: return
        from tkinter import colorchooser
        cur = self.annot.get("fill_color", DEFAULT_HIGHLIGHT_COLOR)
        _, hexcol = colorchooser.askcolor(color=cur, parent=self, title="강조 색상 선택")
        if hexcol and hexcol != cur:
            self.owner._push_undo()
            self.annot["fill_color"] = hexcol
            self.highlight_color_btn.config(bg=hexcol)
            self.owner._on_annot_prop_changed()

    def _delete_shape(self):
        if self.annot is None: return
        self.owner._delete_selected_annot()


# ══════════════════════════════════════════════════════════
#  미리보기 창  (크게보기 + 편집: 삭제·회전·텍스트)
# ══════════════════════════════════════════════════════════
class PreviewWin(tk.Toplevel):
    def __init__(self, parent, pages, start, on_change=None):
        super().__init__(parent)
        self.pages     = pages
        self.idx       = start
        self.photo     = None
        self._rid      = None
        self.on_change = on_change   # 편집 후 부모 갱신 콜백
        self.zoom      = 1.0         # 줌 배율
        self.pan_x     = 0           # 이동 오프셋 X
        self.pan_y     = 0           # 이동 오프셋 Y
        self._drag_sx  = None        # 드래그 시작점
        self._drag_sy  = None

        # ── 편집 모드 (텍스트 객체) ──────────────────────────
        self.edit_mode   = False     # 보기 모드(기본) / 편집 모드
        self.tool        = "select"  # "select" | "text"
        self.selected_id = None      # 선택된 annot id
        self._move_state = None      # 드래그로 이동 중인 annot 정보
        self._shape_draft = None     # 드래그로 도형을 새로 그리는 중인 상태(미리보기용)
        self._resize_state = None    # 핸들을 드래그해 도형 크기/끝점을 조정 중인 상태
        self._clipboard_annot = None # Ctrl+C 로 복사해둔 annot (텍스트/도형 공통)
        # ── Undo / Redo (annotation 편집 전용) ────────────────
        # 스택의 각 항목은 {"page_idx": int, "annots": [...]} 형태로,
        # 실제 변경(생성/삭제/이동/리사이즈/속성변경) 직전의 해당 페이지
        # annots 리스트를 깊은 복사해 담는다 (원본과 절대 공유되지 않음).
        self._undo_stack = []
        self._redo_stack = []
        self._UNDO_LIMIT = 200   # 무한정 쌓이는 것만 방지하는 안전장치
        # 드래그로 이동/리사이즈할 때는 모션 이벤트마다가 아니라, 실제로
        # 처음 좌표가 바뀌는 그 순간에만 스냅샷 1개를 남기기 위한 플래그.
        self._move_snapshot_pending = False
        self._resize_snapshot_pending = False
        # ── 이동(팬) 도구 — 버튼 토글 또는 스페이스바로 임시 활성화 ──
        self._pan_active     = False # 팬 도구가 (버튼/스페이스 무엇으로든) 켜져 있는지
        self._tool_before_pan = "select"  # 팬을 끌 때 되돌아갈 이전 도구
        self._space_key_down  = False
        self._space_hold_pending = None   # 키 반복(auto-repeat)으로 인한 가짜 릴리즈 방지용 after id
        # 마지막 _show() 렌더링 기준 좌표 변환 파라미터 (screen<->pdf 변환용)
        self._sc      = None
        self._cx       = None
        self._cy       = None
        self._cur_pw   = None
        self._cur_ph   = None
        self._cur_rot  = 0

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h   = min(940, sw-60), min(820, sh-60)
        self._windowed_geometry = f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}"  # 창모드 전환 시 복귀할 크기
        self.geometry(self._windowed_geometry)
        self.title("미리보기")
        self.configure(bg=BG)
        self.transient(parent)
        self.grab_set()
        self.focus_set()
        self.resizable(True, True)
        # 텍스트 작업 공간을 넓게 쓰도록 기본은 전체화면으로 시작하고,
        # 화면이 크다고 느끼는 사람은 상단 토글 버튼으로 창모드로 바꿀 수 있다.
        self.is_fullscreen = True
        try:
            self.attributes("-fullscreen", True)
        except tk.TclError:
            self.is_fullscreen = False

        self._build()
        self.after(60, self._show)

        # 속성 패널의 입력창(Entry/Combobox)에 포커스가 있을 때는 아래
        # 단축키들이 가로채면 안 된다 (예: X 좌표에 "-999" 를 입력하려는데
        # "-" 가 축소 단축키로 먼저 소비되는 문제 방지).
        # 텍스트를 선택한 상태에서는 방향키가 페이지 이동 대신 그 텍스트를
        # 바로 이동시킨다 (캔버스를 클릭해 선택하면 포커스가 캔버스로 옮겨가
        # X/Y 입력창에 없기 때문에, 입력창에 포커스가 있을 때만 쓰던 방향키
        # 미세조정이 그 경우엔 전혀 동작하지 않았던 문제를 해결).
        self.bind("<Left>",       lambda e: None if self._focus_in_entry() else self._on_key_left())
        self.bind("<Right>",      lambda e: None if self._focus_in_entry() else self._on_key_right())
        self.bind("<Up>",         lambda e: None if self._focus_in_entry() else self._nudge_selected_y(0.1))
        self.bind("<Down>",       lambda e: None if self._focus_in_entry() else self._nudge_selected_y(-0.1))
        self.bind("<Shift-Left>", lambda e: None if self._focus_in_entry() else self._nudge_selected_x(-1.0))
        self.bind("<Shift-Right>",lambda e: None if self._focus_in_entry() else self._nudge_selected_x(1.0))
        self.bind("<Shift-Up>",   lambda e: None if self._focus_in_entry() else self._nudge_selected_y(1.0))
        self.bind("<Shift-Down>", lambda e: None if self._focus_in_entry() else self._nudge_selected_y(-1.0))
        # Esc 로 창이 닫히지 않게 한다 — 텍스트 입력 중 실수로 창 전체가
        # 닫히는 문제가 있어, 미리보기 창은 우측 상단 ✕ 버튼으로만 닫는다.
        self.bind("<plus>",       lambda e: None if self._focus_in_entry() else self._zoom(1.25))
        self.bind("<equal>",      lambda e: None if self._focus_in_entry() else self._zoom(1.25))
        self.bind("<minus>",      lambda e: None if self._focus_in_entry() else self._zoom(1/1.25))
        self.bind("<0>",          lambda e: None if self._focus_in_entry() else self._zoom_reset())
        self.bind("<Delete>",     lambda e: None if self._focus_in_entry() else self._delete_selected_annot())
        # Ctrl+C/V 로 선택된 텍스트/도형을 복사·붙여넣기 (같은 좌표/크기/
        # 속성 그대로 복제 — 위치는 속성 패널에서 직접 옮기면 됨).
        self.bind("<Control-c>",  lambda e: None if self._focus_in_entry() else self._copy_selected_annot())
        self.bind("<Control-C>",  lambda e: None if self._focus_in_entry() else self._copy_selected_annot())
        self.bind("<Control-v>",  lambda e: None if self._focus_in_entry() else self._paste_annot())
        self.bind("<Control-V>",  lambda e: None if self._focus_in_entry() else self._paste_annot())
        # Ctrl+Z/Y 로 annotation 편집 실행취소/다시실행. X/Y 등 입력창에
        # 포커스가 있을 때는(Ctrl+C/V 와 동일한 규칙) 가로채지 않아 그
        # 입력창 자체의 기본 동작이 우선되게 한다.
        self.bind("<Control-z>",  lambda e: None if self._focus_in_entry() else self._undo())
        self.bind("<Control-Z>",  lambda e: None if self._focus_in_entry() else self._undo())
        self.bind("<Control-y>",  lambda e: None if self._focus_in_entry() else self._redo())
        self.bind("<Control-Y>",  lambda e: None if self._focus_in_entry() else self._redo())
        # 스페이스바: 누르고 있는 동안 임시로 팬(이동) 도구로 전환, 떼면 원래
        # 도구로 복귀. 이미 팬 버튼으로 켜둔 상태라면 한 번 눌렀다 떼는 것만
        # 으로 팬을 끈다(버튼을 다시 누르는 것과 동일한 효과).
        self.bind("<KeyPress-space>",   self._on_space_press)
        self.bind("<KeyRelease-space>", self._on_space_release)

    def _build(self):
        # ── 상단 타이틀 바 ───────────────────────────────
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=20, pady=(14, 0))
        self.title_lbl = tk.Label(top, text="", font=FONT_B,
                                  bg=BG, fg=TEXT)
        self.title_lbl.pack(side="left")
        # ── 창 컨트롤(최대화/닫기) — Windows 기본 타이틀바처럼 버튼끼리
        # 서로 붙은 넓은 사각형 버튼 + 마우스오버 시 배경 강조.
        winctl = tk.Frame(top, bg=BG)
        winctl.pack(side="right")

        self.close_btn = tk.Button(winctl, text="✕", command=self.destroy,
                  bg=BG, fg=TEXT_DIM, font=(FM, 12),
                  relief="flat", bd=0, highlightthickness=0,
                  cursor="hand2", width=4, pady=8)
        self.close_btn.pack(side="right")
        self.close_btn.bind("<Enter>", lambda e: self.close_btn.config(bg="#E81123", fg="white"))
        self.close_btn.bind("<Leave>", lambda e: self.close_btn.config(bg=BG, fg=TEXT_DIM))

        # 시작이 전체화면이므로 강조색으로 표시 (호버 배경과는 별개로 유지).
        self.fullscreen_btn = tk.Button(winctl, text="□", command=self._toggle_fullscreen,
                  bg=BG, fg=ACCENT, font=(FM, 11),
                  relief="flat", bd=0, highlightthickness=0,
                  cursor="hand2", width=4, pady=8)
        self.fullscreen_btn.pack(side="right")
        self.fullscreen_btn.bind("<Enter>", lambda e: self.fullscreen_btn.config(bg=_shade(BG, 0.9)))
        self.fullscreen_btn.bind("<Leave>", lambda e: self.fullscreen_btn.config(bg=BG))
        self.edit_btn = tk.Button(top, text="✎ 편집 모드", command=self._toggle_edit,
                  bg=TOOLBAR, fg=TEXT_DIM, font=FONT_B,
                  relief="flat", padx=12, pady=5, cursor="hand2",
                  bd=0, activebackground=_shade(TOOLBAR, 0.92))
        self.edit_btn.pack(side="right", padx=(0,10))

        # ── 편집 툴바 (편집 모드일 때만 표시) ────────────
        self.edit_toolbar = tk.Frame(self, bg=TOOLBAR)
        self.tool_btns = {}
        for key, label in [("select","🖱 선택"), ("text","T 텍스트"),
                           ("rect","▭ 사각형"), ("arrow","↗ 화살표"), ("highlight","🖊 강조"),
                           ("pan","✋ 이동")]:
            # "이동" 은 다른 도구처럼 클릭 시 즉시 전환되는 게 아니라, 다시
            # 누르면 꺼지는 토글 버튼(눌러서 켬 → 다시 눌러서 꺼짐)이다.
            cmd = self._toggle_pan_tool if key == "pan" else (lambda k=key: self._set_tool(k))
            b = tk.Button(self.edit_toolbar, text=label,
                          command=cmd,
                          bg=TOOLBAR, fg=TEXT_DIM, font=FONT_B,
                          relief="flat", padx=14, pady=6, cursor="hand2",
                          bd=0, activebackground=_shade(TOOLBAR, 0.92))
            b.pack(side="left", padx=(20 if key=="select" else 4, 4), pady=6)
            self.tool_btns[key] = b

        # ── 이미지 캔버스 + 우측 속성 패널 ──────────────────
        mid = tk.Frame(self, bg=BG)
        self.preview_cf = mid
        mid.pack(fill="both", expand=True)
        # 속성 패널을 담는 고정폭 컨테이너. 선택할 때마다 이 안에서만
        # pack()/pack_forget() 하고, 컨테이너 자체는 편집모드가 켜져있는
        # 동안 항상 폭을 차지하고 있게 해서, 텍스트/도형을 선택·해제할
        # 때마다 캔버스 폭이 바뀌어 PDF 미리보기가 좌우로 밀리는 문제를
        # 없앤다 (편집모드 진입/이탈 시에만 한 번 자리를 잡는다).
        self.side_panel_holder = tk.Frame(mid, bg=BG, width=230)
        self.side_panel_holder.pack_propagate(False)
        self.prop_panel  = TextPropPanel(self.side_panel_holder, owner=self)
        self.shape_panel = ShapePropPanel(self.side_panel_holder, owner=self)

        cf = tk.Frame(mid, bg=BG)
        cf.pack(side="left", fill="both", expand=True, padx=30, pady=12)
        self.canvas = tk.Canvas(cf, bg=BG, bd=0, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>",      self._on_resize)
        self.canvas.bind("<MouseWheel>",
                         lambda e: self._zoom(1.15 if e.delta > 0 else 1/1.15))
        self.canvas.bind("<ButtonPress-1>",  self._on_canvas_press)
        self.canvas.bind("<B1-Motion>",      self._on_canvas_motion)
        self.canvas.bind("<ButtonRelease-1>",self._on_canvas_release)

        # ── 하단 컨트롤 바 (네비 + 편집) ────────────────
        nav = tk.Frame(self, bg=TOOLBAR, pady=10)
        nav.pack(fill="x")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", side="bottom")

        # 이전 / 다음
        self.btn_prev = tk.Button(nav, text="◀", command=lambda: self._go(-1),
                                  bg=TOOLBAR, fg=TEXT_DIM, font=FONT_B,
                                  relief="flat", padx=14, pady=8, cursor="hand2",
                                  bd=0, activebackground=_shade(TOOLBAR, 0.92))
        self.btn_prev.pack(side="left", padx=(20, 4))

        self.page_lbl = tk.Label(nav, text="", font=FONT_B,
                                 bg=TOOLBAR, fg=TEXT)
        self.page_lbl.pack(side="left", padx=8)

        self.btn_next = tk.Button(nav, text="▶", command=lambda: self._go(1),
                                  bg=TOOLBAR, fg=TEXT_DIM, font=FONT_B,
                                  relief="flat", padx=14, pady=8, cursor="hand2",
                                  bd=0, activebackground=_shade(TOOLBAR, 0.92))
        self.btn_next.pack(side="left", padx=(4, 20))

        # ── 편집 버튼들 (가운데) ─────────────────────────
        edit = tk.Frame(nav, bg=TOOLBAR)
        edit.pack(side="left", expand=True)

        for txt, cmd, bg, fg in [
            ("↺ 왼쪽 90°", lambda: self._rotate(-90), TOOLBAR, TEXT),
            ("↻ 오른쪽 90°", lambda: self._rotate(90),  TOOLBAR, TEXT),
            ("🗑 이 페이지 삭제", self._delete,         DANGER, "white"),
        ]:
            b = tk.Button(edit, text=txt, command=cmd, bg=bg,
                          fg=fg, font=FONT, relief="flat",
                          padx=12, pady=7, cursor="hand2", bd=0)
            b.pack(side="left", padx=5)

        # ── 줌 버튼들 ────────────────────────────────────
        zoom_fr = tk.Frame(nav, bg=TOOLBAR)
        zoom_fr.pack(side="right", padx=(0, 12))

        tk.Button(zoom_fr, text="−", command=lambda: self._zoom(1/1.25),
                  bg=TOOLBAR, fg=TEXT_DIM, font=(FM, 13, "bold"),
                  relief="flat", padx=10, pady=6, cursor="hand2",
                  bd=0, activebackground=_shade(TOOLBAR, 0.92)).pack(side="left", padx=2)

        self.zoom_lbl = tk.Label(zoom_fr, text="100%", width=5,
                                 font=FONT, bg=TOOLBAR, fg=TEXT)
        self.zoom_lbl.pack(side="left")

        tk.Button(zoom_fr, text="+", command=lambda: self._zoom(1.25),
                  bg=TOOLBAR, fg=TEXT_DIM, font=(FM, 13, "bold"),
                  relief="flat", padx=10, pady=6, cursor="hand2",
                  bd=0, activebackground=_shade(TOOLBAR, 0.92)).pack(side="left", padx=2)

        # 닫기
        tk.Button(nav, text="닫기", command=self.destroy,
                  bg=ACCENT, fg="white", font=FONT_B,
                  relief="flat", padx=18, pady=8, cursor="hand2",
                  bd=0).pack(side="right", padx=20)

    def _on_resize(self, _=None):
        if self._rid: self.after_cancel(self._rid)
        self._rid = self.after(80, self._show)

    def _show(self):
        self._sc = None   # 렌더링 실패 시 좌표 변환/클릭 처리가 동작하지 않도록 초기화
        n = len(self.pages)
        if n == 0:
            self.destroy(); return
        self.idx = max(0, min(self.idx, n-1))
        pg = self.pages[self.idx]

        fname = os.path.basename(pg["src"])
        self.title_lbl.config(text=f"{fname}  —  p.{pg['pidx']+1}")
        self.page_lbl.config(text=f"{self.idx+1} / {n}")
        self.btn_prev.config(state="normal" if self.idx > 0   else "disabled")
        self.btn_next.config(state="normal" if self.idx < n-1 else "disabled")

        self.canvas.delete("all")
        self.zoom_lbl.config(text=f"{int(self.zoom*100)}%")
        self.update_idletasks()
        cw = max(self.canvas.winfo_width(), 400)
        ch = max(self.canvas.winfo_height(), 300)

        if not PREVIEW_OK:
            self.canvas.create_text(cw//2, ch//2,
                text="pip install pymupdf pillow 필요",
                fill="#998", font=FONT_B, justify="center")
            return
        try:
            doc  = fitz.open(pg["src"])
            page = doc[pg["pidx"]]
            pw_pt, ph_pt = page.rect.width, page.rect.height
            base_sc = min(cw*0.86/pw_pt, ch*0.90/ph_pt)
            base_sc = max(base_sc, 0.4)
            sc   = base_sc * self.zoom
            pix  = page.get_pixmap(matrix=fitz.Matrix(sc, sc), alpha=False)
            doc.close()
            img  = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            rot  = pg.get("rot", 0)
            if rot: img = img.rotate(-rot, expand=True)
            self.photo = ImageTk.PhotoImage(img)

            iw, ih = img.width, img.height
            ix = cw//2 + self.pan_x
            iy = ch//2 + self.pan_y
            # 부드러운 그림자
            for d, col in [(8,SH1),(5,SH2),(2,"#F2F2F2")]:
                self.canvas.create_rectangle(
                    ix-iw//2+d, iy-ih//2+d, ix+iw//2+d, iy+ih//2+d,
                    fill=col, outline="")
            # 흰 테두리 + 이미지
            self.canvas.create_rectangle(
                ix-iw//2-3, iy-ih//2-3, ix+iw//2+3, iy+ih//2+3,
                fill="white", outline=BORDER, width=1)
            self.canvas.create_image(ix, iy, image=self.photo)

            # 좌표 변환 상태 저장 (클릭/드래그에서 screen_to_pdf 에 사용)
            self._sc      = sc
            self._cx      = ix
            self._cy      = iy
            self._cur_pw  = pw_pt
            self._cur_ph  = ph_pt
            self._cur_rot = rot
            self._draw_annots(pg)
        except Exception as e:
            self.canvas.create_text(cw//2, ch//2, text=f"오류:\n{e}",
                                    fill="#a88", font=FONT, justify="center")

    def _go(self, d):
        if 0 <= self.idx+d < len(self.pages):
            self.idx += d
            self.pan_x = 0; self.pan_y = 0   # 페이지 바뀌면 위치 초기화
            self.selected_id = None
            self._move_state = None
            self.prop_panel.pack_forget()
            self._show()

    def _zoom(self, factor):
        self.zoom = max(0.25, min(4.0, self.zoom * factor))
        self.zoom_lbl.config(text=f"{int(self.zoom*100)}%")
        self._show()

    # ── 방향키: 선택된 텍스트가 있으면 이동, 없으면 페이지 이동 ─────
    def _on_key_left(self):
        if self.edit_mode and self.selected_id is not None:
            self._nudge_selected_x(-0.1)
        else:
            self._go(-1)

    def _on_key_right(self):
        if self.edit_mode and self.selected_id is not None:
            self._nudge_selected_x(0.1)
        else:
            self._go(1)

    def _nudge_selected_x(self, delta_mm):
        if self.selected_id is None: return
        self.prop_panel._nudge_x(delta_mm)

    def _nudge_selected_y(self, delta_mm):
        if self.selected_id is None: return
        self.prop_panel._nudge_y(delta_mm)

    def _zoom_reset(self):
        self.zoom  = 1.0
        self.pan_x = 0; self.pan_y = 0
        self.zoom_lbl.config(text="100%")
        self._show()

    # ── 캔버스 드래그 — 편집 모드/도구에 따라 분기 ────────────
    def _on_canvas_press(self, e):
        if self.edit_mode and self.tool == "text":
            self._create_text_at(e.x, e.y)
            return
        if self.edit_mode and self.tool in ("rect", "arrow", "highlight"):
            self._shape_draft = {"tool": self.tool, "sx0": e.x, "sy0": e.y, "item": None}
            return
        if self.edit_mode and self.tool == "select":
            # 속성 패널의 입력창에 포커스가 남아있으면 Delete 등 단축키가
            # 캔버스가 아니라 그 입력창으로 먼저 소비돼버린다. 캔버스를
            # 클릭하는 순간 포커스를 캔버스로 되돌려 단축키가 항상 먹게 한다.
            self.canvas.focus_set()
            handle = self._handle_hit_test(e.x, e.y)
            if handle is not None:
                self._resize_state = handle
                # 실제로 크기가 바뀌기 시작하는 첫 모션 이벤트에서만 실행취소
                # 스냅샷을 남긴다(클릭만 하고 끝나면 스냅샷 자체가 필요 없음).
                self._resize_snapshot_pending = True
                return
            hit = self._hit_test(e.x, e.y)
            if hit is not None:
                self._select_annot(hit["id"])
                if self._sc is not None:
                    px_pdf, py_pdf = screen_to_pdf(
                        e.x, e.y, self._cur_pw, self._cur_ph,
                        self._cur_rot, self._sc, self._cx, self._cy)
                    ref_x, ref_y = _annot_ref_point(hit)
                    self._move_state = {
                        "annot_id": hit["id"],
                        "off_x": ref_x - px_pdf,
                        "off_y": ref_y - py_pdf,
                    }
                    # 리사이즈와 동일하게, 실제로 위치가 바뀌기 시작하는 첫
                    # 모션 이벤트에서만 스냅샷 1개를 남긴다.
                    self._move_snapshot_pending = True
                return
            else:
                self._select_annot(None)
                # 선택 도구에서는 빈 공간을 드래그해도 화면이 팬되지 않는다 —
                # 팬은 이제 전용 "이동" 버튼이나 스페이스바로만 한다.
                return
        self._pan_start(e)

    def _on_canvas_motion(self, e):
        if self._shape_draft is not None:
            self._update_shape_draft(e)
            return
        if self._resize_state is not None:
            self._resize_annot(e)
            return
        if self._move_state is not None:
            self._drag_annot(e)
            return
        self._pan_move(e)

    def _on_canvas_release(self, e):
        if self._shape_draft is not None:
            self._finish_shape_draft(e)
            return
        if self._resize_state is not None:
            self._resize_state = None
            self._resize_snapshot_pending = False
            if self.on_change: self.on_change()
            return
        if self._move_state is not None:
            self._move_state = None
            self._move_snapshot_pending = False
            if self.on_change: self.on_change()
            return
        self._pan_end(e)

    # ── 도형 드래그 생성 (마우스로 크기를 직접 지정) ───────────
    def _update_shape_draft(self, e):
        d = self._shape_draft
        if d["item"] is not None:
            self.canvas.delete(d["item"])
        x0, y0, x1, y1 = d["sx0"], d["sy0"], e.x, e.y
        if d["tool"] == "arrow":
            d["item"] = self.canvas.create_line(
                x0, y0, x1, y1, fill=ACCENT, width=2, dash=(4,2),
                arrow="last", tags=("shape_draft",))
        else:
            d["item"] = self.canvas.create_rectangle(
                min(x0,x1), min(y0,y1), max(x0,x1), max(y0,y1),
                outline=ACCENT, width=2, dash=(4,2), tags=("shape_draft",))

    def _finish_shape_draft(self, e):
        d = self._shape_draft
        self._shape_draft = None
        if d["item"] is not None:
            self.canvas.delete(d["item"])
        if self._sc is None: return
        sx0, sy0, sx1, sy1 = d["sx0"], d["sy0"], e.x, e.y
        if abs(sx1-sx0) < 4 and abs(sy1-sy0) < 4:
            return   # 너무 작게 드래그하면(사실상 클릭) 도형을 만들지 않음
        x0_pt, y0_pt = screen_to_pdf(sx0, sy0, self._cur_pw, self._cur_ph,
                                      self._cur_rot, self._sc, self._cx, self._cy)
        x1_pt, y1_pt = screen_to_pdf(sx1, sy1, self._cur_pw, self._cur_ph,
                                      self._cur_rot, self._sc, self._cx, self._cy)
        pg = self.pages[self.idx]
        tool = d["tool"]
        if tool == "rect":
            annot = {"id": next(_id_gen), "type": "rect",
                     "x0": min(x0_pt,x1_pt), "y0": min(y0_pt,y1_pt),
                     "x1": max(x0_pt,x1_pt), "y1": max(y0_pt,y1_pt),
                     "line_color": DEFAULT_RECT_LINE_COLOR, "line_width": DEFAULT_SHAPE_LINE_WIDTH,
                     "fill_color": DEFAULT_SHAPE_FILL_COLOR, "fill_enabled": False}
        elif tool == "highlight":
            annot = {"id": next(_id_gen), "type": "highlight",
                     "x0": min(x0_pt,x1_pt), "y0": min(y0_pt,y1_pt),
                     "x1": max(x0_pt,x1_pt), "y1": max(y0_pt,y1_pt),
                     "fill_color": DEFAULT_HIGHLIGHT_COLOR}
        else:   # arrow: 시작->끝 방향이 의미가 있으므로 정규화하지 않음
            annot = {"id": next(_id_gen), "type": "arrow",
                     "x0": x0_pt, "y0": y0_pt, "x1": x1_pt, "y1": y1_pt,
                     "line_color": DEFAULT_SHAPE_LINE_COLOR, "line_width": DEFAULT_SHAPE_LINE_WIDTH}
        self._push_undo()
        pg.setdefault("annots", []).append(annot)
        self._select_annot(annot["id"])
        if self.on_change: self.on_change()
        # 텍스트와 마찬가지로, 하나 만들고 나면 선택 도구로 자동 전환해서
        # 이어지는 드래그가 계속 새 도형을 만들지 않게 한다.
        self._set_tool("select")

    # ── 팬(이동) ─────────────────────────────────────────────
    def _pan_start(self, e):
        self._drag_sx = e.x
        self._drag_sy = e.y
        self.canvas.config(cursor="fleur")   # 십자 이동 커서

    def _pan_move(self, e):
        if self._drag_sx is None: return
        dx = e.x - self._drag_sx
        dy = e.y - self._drag_sy
        self.pan_x += dx
        self.pan_y += dy
        self._drag_sx = e.x
        self._drag_sy = e.y
        if self._sc is None:
            self._show()
            return
        # 팬은 이미지 자체가 바뀌는 게 아니라 위치만 바뀌는 것이므로, 매
        # 프레임 PDF를 다시 열어 렌더링(_show)하면 "지웠다가 다시 그리는"
        # 순간이 보여 깜빡인다. 캔버스에 이미 있는 항목들을 그만큼만
        # 이동시키고, 좌표 변환 기준점(_cx/_cy)도 같이 갱신한다.
        self.canvas.move("all", dx, dy)
        self._cx += dx
        self._cy += dy

    def _pan_end(self, e):
        self._drag_sx = None
        self._drag_sy = None
        self.canvas.config(cursor="")

    # ── 전체화면 / 창모드 전환 ─────────────────────────────────
    def _toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        try:
            self.attributes("-fullscreen", self.is_fullscreen)
        except tk.TclError:
            self.is_fullscreen = False
        if not self.is_fullscreen:
            self.geometry(self._windowed_geometry)
        # 아이콘 자체는 항상 같은 사각형(□)이고, 폰트별 복원 아이콘 글리프
        # 지원 여부에 기대지 않기 위해 현재 전체화면 상태만 강조 색으로 표시한다.
        self.fullscreen_btn.config(fg=ACCENT if self.is_fullscreen else TEXT_DIM)

    # ── 편집 모드 / 도구 선택 ─────────────────────────────────
    def _toggle_edit(self):
        self.edit_mode = not self.edit_mode
        self.edit_btn.config(bg=ACCENT if self.edit_mode else TOOLBAR,
                              fg="white" if self.edit_mode else TEXT_DIM)
        if self.edit_mode:
            self.edit_toolbar.pack(fill="x", before=self.preview_cf)
            # 속성 패널 자리를 편집모드 진입 시 미리 확보해둔다 — 선택할
            # 때마다 새로 자리를 만들면 그때마다 캔버스 폭이 바뀌어 PDF가
            # 좌우로 밀려 보이는 문제가 있었다.
            self.side_panel_holder.pack(side="right", fill="y")
            self._set_tool(self.tool)
        else:
            self.edit_toolbar.pack_forget()
            self._select_annot(None)
            self.side_panel_holder.pack_forget()
            # 편집모드를 나가면 팬 관련 임시 상태도 함께 정리한다.
            self._pan_active = False
            self._space_key_down = False
            if self._space_hold_pending is not None:
                self.after_cancel(self._space_hold_pending)
                self._space_hold_pending = None
        self._show()

    def _set_tool(self, key):
        self.tool = key
        if key != "pan":
            self._pan_active = False
        for k, b in self.tool_btns.items():
            active = (k == key)
            b.config(bg=ACCENT if active else TOOLBAR,
                     fg="white" if active else TEXT_DIM)
        if key == "text":
            cursor = "xterm"
        elif key in ("rect", "arrow", "highlight"):
            cursor = "crosshair"
        elif key == "pan":
            cursor = "fleur"
        else:
            cursor = ""
        self.canvas.config(cursor=cursor)

    # ── 이동(팬) 도구 켬/끔 ────────────────────────────────
    def _enable_pan(self):
        if self._pan_active: return
        self._tool_before_pan = self.tool
        self._pan_active = True
        self._set_tool("pan")   # key=="pan" 이므로 _set_tool 내부에서 _pan_active 를 건드리지 않음

    def _disable_pan(self):
        if not self._pan_active: return
        self._pan_active = False
        self._set_tool(self._tool_before_pan or "select")

    def _toggle_pan_tool(self):
        """도구모음의 '이동' 버튼: 누르면 켜지고, 다시 누르면 꺼진다."""
        if self._pan_active:
            self._disable_pan()
        else:
            self._enable_pan()

    # ── 스페이스바로 임시 팬(누르는 동안만) / 팬 토글 끄기 ────
    def _on_space_press(self, e):
        if not self.edit_mode or self._focus_in_entry():
            return
        if self._space_hold_pending is not None:
            # 키보드 자동반복(auto-repeat)으로 생긴 릴리즈 예약을 취소 —
            # 실제로는 계속 눌려있는 중이므로 아무 것도 바꾸지 않는다.
            self.after_cancel(self._space_hold_pending)
            self._space_hold_pending = None
            return
        if self._space_key_down:
            return
        self._space_key_down = True
        self._enable_pan()

    def _on_space_release(self, e):
        if self._focus_in_entry() or not self._space_key_down:
            return
        # 자동반복 중 오는 가짜 릴리즈를 걸러내기 위해 살짝 지연 후 처리 —
        # 그 사이에 다음 KeyPress-space 가 오면 위에서 예약을 취소한다.
        self._space_hold_pending = self.after(35, self._finish_space_release)

    def _finish_space_release(self):
        self._space_hold_pending = None
        self._space_key_down = False
        self._disable_pan()

    def _focus_in_entry(self):
        """속성 패널의 입력창에 포커스가 있는지 확인 (단축키 충돌 방지용)."""
        w = self.focus_get()
        return isinstance(w, (tk.Entry, tk.Spinbox, tk.Text, ttk.Entry, ttk.Combobox))

    # ── Undo / Redo (annotation 편집 전용) ────────────────────
    def _push_undo(self):
        """실제 변경(생성/삭제/이동/리사이즈/속성변경) 직전에 한 번만
        호출한다. 현재 페이지의 annots 를 깊은 복사해 실행취소 스택에
        쌓고, 새로운 편집이 시작된 것이므로 redo 스택은 비운다(일반적인
        편집기와 동일한 규칙)."""
        pg = self.pages[self.idx]
        self._undo_stack.append({
            "page_idx": self.idx,
            "annots": copy.deepcopy(pg.get("annots", [])),
        })
        if len(self._undo_stack) > self._UNDO_LIMIT:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _restore_snapshot(self, entry):
        """스냅샷을 실제 페이지에 되돌리고 화면/속성패널을 갱신한다."""
        idx = entry["page_idx"]
        if not (0 <= idx < len(self.pages)):
            return
        self.pages[idx]["annots"] = entry["annots"]
        self.idx = idx
        sel = self.selected_id
        still_exists = sel is not None and any(
            a["id"] == sel for a in self.pages[idx].get("annots", []))
        if not still_exists:
            self.selected_id = None
        self._show()
        self._select_annot(self.selected_id)
        if self.on_change: self.on_change()

    def _undo(self):
        if not self._undo_stack: return
        cur_pg = self.pages[self.idx]
        self._redo_stack.append({
            "page_idx": self.idx,
            "annots": copy.deepcopy(cur_pg.get("annots", [])),
        })
        entry = self._undo_stack.pop()
        self._restore_snapshot(entry)

    def _redo(self):
        if not self._redo_stack: return
        cur_pg = self.pages[self.idx]
        self._undo_stack.append({
            "page_idx": self.idx,
            "annots": copy.deepcopy(cur_pg.get("annots", [])),
        })
        entry = self._redo_stack.pop()
        self._restore_snapshot(entry)

    # ── annot(텍스트) 선택/생성/이동/삭제 ─────────────────────
    # ── 도형 크기/끝점 조정 핸들 ────────────────────────────
    HANDLE_R = 6   # 핸들 히트테스트 반경(px)

    def _shape_handle_points(self, a):
        """도형의 조정 가능한 기준점들을 (이름, (x_pt,y_pt)) 목록으로."""
        if a.get("type") == "arrow":
            return [("p0", (a["x0"], a["y0"])), ("p1", (a["x1"], a["y1"]))]
        return [("x0y0", (a["x0"], a["y0"])), ("x1y0", (a["x1"], a["y0"])),
                ("x0y1", (a["x0"], a["y1"])), ("x1y1", (a["x1"], a["y1"]))]

    def _handle_hit_test(self, ex, ey):
        """선택된 도형(사각형/화살표)의 핸들 위를 클릭했는지 확인한다.
        핸들은 선택된 도형에만 그려지므로, 그 도형에 대해서만 판정한다."""
        if self._sc is None or self.selected_id is None:
            return None
        a = self._find_annot(self.selected_id)
        if a is None or a.get("type") not in ("rect", "arrow"):
            return None
        for name, (x_pt, y_pt) in self._shape_handle_points(a):
            sx, sy = pdf_to_screen(x_pt, y_pt, self._cur_pw, self._cur_ph,
                                    self._cur_rot, self._sc, self._cx, self._cy)
            if abs(sx-ex) <= self.HANDLE_R and abs(sy-ey) <= self.HANDLE_R:
                return {"annot_id": a["id"], "handle": name}
        return None

    def _resize_annot(self, e):
        if self._sc is None or self._resize_state is None: return
        a = self._find_annot(self._resize_state["annot_id"])
        if a is None: return
        if self._resize_snapshot_pending:
            self._push_undo()
            self._resize_snapshot_pending = False
        handle = self._resize_state["handle"]
        x_pt, y_pt = screen_to_pdf(e.x, e.y, self._cur_pw, self._cur_ph,
                                    self._cur_rot, self._sc, self._cx, self._cy)
        if a.get("type") == "arrow":
            if handle == "p0": a["x0"], a["y0"] = x_pt, y_pt
            else:              a["x1"], a["y1"] = x_pt, y_pt
        else:
            if handle in ("x0y0", "x0y1"): a["x0"] = x_pt
            else:                          a["x1"] = x_pt
            if handle in ("x0y0", "x1y0"): a["y0"] = y_pt
            else:                          a["y1"] = y_pt
            # 반대쪽 핸들을 넘어서 드래그하면 x0<x1, y0<y1 이 되도록 값을
            # 맞바꾸고, 다음 프레임에도 같은 핸들을 계속 잡고 있을 수 있게
            # 그 핸들이 가리키는 이름도 함께 갱신한다.
            if a["x0"] > a["x1"]:
                a["x0"], a["x1"] = a["x1"], a["x0"]
                handle = handle.replace("x0","tmp").replace("x1","x0").replace("tmp","x1")
            if a["y0"] > a["y1"]:
                a["y0"], a["y1"] = a["y1"], a["y0"]
                handle = handle.replace("y0","tmp").replace("y1","y0").replace("tmp","y1")
            self._resize_state["handle"] = handle
        self.shape_panel.refresh_xy_only()
        self._redraw_annots()

    def _hit_test(self, ex, ey):
        """캔버스 좌표(ex,ey) 위에 있는 현재 페이지의 annot 을 찾는다.
        사각형/강조처럼 채우기가 없을 수 있는 도형은 Tk 캔버스 자체
        히트테스트(find_overlapping)가 빈 내부를 "아이템 없음"으로
        취급해버리므로(채워진 경우에만 내부 클릭이 히트로 잡힘), 그
        두 타입은 화면 좌표 bbox 로 직접 판정한다."""
        pg = self.pages[self.idx]
        annots = pg.get("annots", [])
        if self._sc is not None:
            for a in reversed(annots):
                if a.get("type") in ("rect", "highlight"):
                    sx0, sy0, sx1, sy1 = self._shape_screen_corners(a)
                    if (min(sx0,sx1)-2 <= ex <= max(sx0,sx1)+2 and
                            min(sy0,sy1)-2 <= ey <= max(sy0,sy1)+2):
                        return a
        lookup = {a["id"]: a for a in annots}
        for item in reversed(self.canvas.find_overlapping(ex-2, ey-2, ex+2, ey+2)):
            for t in self.canvas.gettags(item):
                if t.startswith("annot_"):
                    aid = int(t.split("_")[1])
                    if aid in lookup:
                        return lookup[aid]
        return None

    def _cur_page(self):
        return self.pages[self.idx]

    def _find_annot(self, aid):
        for a in self._cur_page().get("annots", []):
            if a["id"] == aid:
                return a
        return None

    def _redraw_annots(self):
        """페이지 배경(비트맵)은 그대로 두고 annot 오버레이만 다시 그린다.
        선택/이동/속성변경처럼 배경이 바뀌지 않는 갱신에서 매번 PDF를
        다시 렌더링(_show)하면 드래그 중 깜빡임·끊김이 생기므로, 이 경량
        경로를 대신 쓴다. 줌/팬/페이지이동/회전처럼 배경 자체가 바뀔 때만
        _show() 의 전체 재렌더링이 필요하다."""
        if self._sc is None: return
        self.canvas.delete("annot")
        self._draw_annots(self._cur_page())

    def _select_annot(self, aid):
        self.selected_id = aid
        annot = self._find_annot(aid) if aid is not None else None
        self.prop_panel.pack_forget()
        self.shape_panel.pack_forget()
        if annot is not None:
            pg = self._cur_page()
            panel = self.prop_panel if annot.get("type") == "text" else self.shape_panel
            panel.show_annot(annot, pg.get("page_w_pt"), pg.get("page_h_pt"))
            panel.pack(side="right", fill="y")
        self._redraw_annots()

    def _on_annot_prop_changed(self):
        """속성 패널에서 값이 바뀌었을 때 캔버스에 즉시 반영 (배경 재렌더링 없이)."""
        self._redraw_annots()
        if self.on_change: self.on_change()

    def _create_text_at(self, ex, ey):
        """클릭 즉시 기본 텍스트로 객체를 만들고 선택한 뒤, 속성 패널의
        '내용' 입력창에 포커스를 옮겨 바로 타이핑해서 바꿀 수 있게 한다
        (팝업 대화상자를 거치지 않아 생성 흐름이 한 단계 줄어든다)."""
        if self._sc is None: return
        x_pt, y_pt = screen_to_pdf(ex, ey, self._cur_pw, self._cur_ph,
                                    self._cur_rot, self._sc, self._cx, self._cy)
        pg = self.pages[self.idx]
        annot = {
            "id": next(_id_gen), "type": "text", "text": DEFAULT_ANNOT_TEXT,
            "x": x_pt, "y": y_pt,
            "font": DEFAULT_ANNOT_FONT, "font_size": DEFAULT_ANNOT_SIZE,
            "color": DEFAULT_ANNOT_COLOR, "bold": False, "italic": False,
            "align": "left", "rotation": 0.0,
        }
        self._push_undo()
        pg.setdefault("annots", []).append(annot)
        self._select_annot(annot["id"])
        self.prop_panel.focus_content_for_edit()
        if self.on_change: self.on_change()
        # 텍스트 도구를 계속 켜둔 채로 두면 화면을 클릭할 때마다 새 텍스트가
        # 계속 생겨버린다. 하나 만들고 나면 선택 도구로 자동 전환해서,
        # 이어지는 클릭은 (재)선택/이동/빈 곳 클릭으로 동작하게 한다.
        self._set_tool("select")

    def _drag_annot(self, e):
        if self._sc is None or self._move_state is None: return
        a = self._find_annot(self._move_state["annot_id"])
        if a is None: return
        if self._move_snapshot_pending:
            self._push_undo()
            self._move_snapshot_pending = False
        px_pdf, py_pdf = screen_to_pdf(e.x, e.y, self._cur_pw, self._cur_ph,
                                        self._cur_rot, self._sc, self._cx, self._cy)
        ref_x = px_pdf + self._move_state["off_x"]
        ref_y = py_pdf + self._move_state["off_y"]
        _move_annot_to(a, ref_x, ref_y)
        panel = self.prop_panel if a.get("type") == "text" else self.shape_panel
        panel.refresh_xy_only()
        self._redraw_annots()

    def _delete_selected_annot(self, e=None):
        if self.selected_id is None: return
        pg = self.pages[self.idx]
        self._push_undo()
        pg["annots"] = [a for a in pg.get("annots", []) if a["id"] != self.selected_id]
        self.selected_id = None
        self.prop_panel.pack_forget()
        self.shape_panel.pack_forget()
        self._redraw_annots()
        if self.on_change: self.on_change()

    def _copy_selected_annot(self, e=None):
        """선택된 텍스트/도형을 내부 클립보드에 복사한다(다른 페이지로
        이동해서 붙여넣기도 가능)."""
        if self.selected_id is None: return
        a = self._find_annot(self.selected_id)
        if a is not None:
            self._clipboard_annot = dict(a)

    def _paste_annot(self, e=None):
        """복사해둔 텍스트/도형을 같은 좌표·크기·속성 그대로 현재
        페이지에 붙여넣는다(위치 자체는 필요하면 속성 패널에서 옮기면
        됨). 위치를 살짝 어긋나게 하지 않고 원본과 정확히 같은 자리에
        둔다."""
        if self._clipboard_annot is None: return
        pg = self.pages[self.idx]
        new_annot = dict(self._clipboard_annot)
        new_annot["id"] = next(_id_gen)
        self._push_undo()
        pg.setdefault("annots", []).append(new_annot)
        self._select_annot(new_annot["id"])
        if self.on_change: self.on_change()

    def _draw_annots(self, pg):
        for a in pg.get("annots", []):
            t = a.get("type")
            if t == "text":
                self._draw_text_annot(a)
            elif t == "rect":
                self._draw_rect_annot(a)
            elif t == "highlight":
                self._draw_highlight_annot(a)
            elif t == "arrow":
                self._draw_arrow_annot(a)

    def _draw_text_annot(self, a):
        px, py = pdf_to_screen(a["x"], a["y"], self._cur_pw, self._cur_ph,
                                self._cur_rot, self._sc, self._cx, self._cy)
        style_parts = []
        if a.get("bold"):   style_parts.append("bold")
        if a.get("italic"): style_parts.append("italic")
        style = " ".join(style_parts) if style_parts else "normal"
        size_pt = a.get("font_size", DEFAULT_ANNOT_SIZE)
        size_px = max(1, int(round(size_pt * self._sc)))   # 음수=픽셀 크기(줌에 정확히 비례)
        font_spec = (a.get("font", DEFAULT_ANNOT_FONT), -size_px, style)
        # 텍스트 자체 회전(annot["rotation"])과 페이지 회전(pg["rot"])은
        # 서로 별개의 값이며 섞이지 않는다. tk canvas 의 angle 은
        # 반시계방향(+)이라, 이 프로그램의 페이지 회전 규약(시계방향 +)과
        # 표시 방향을 통일하기 위해 부호를 반전해서 넘긴다.
        angle = (-a.get("rotation", 0.0)) % 360
        # 정렬(align)은 X 좌표를 기준선으로 해서 텍스트가 좌/가운데/우측 중
        # 어느 쪽을 그 선에 맞출지 결정한다 — anchor 를 그에 맞게 바꾸고
        # justify 를 같이 쓰면, 여러 줄일 때도 각 줄이 (너비가 달라도) 이
        # 기준선에 맞춰 정렬된다(anchor 로 정한 기준점이 가장 넓은 줄
        # 기준으로 잡히고, justify 가 그 안에서 각 줄을 맞추기 때문에
        # 결과적으로 모든 줄이 X 기준선에 정렬됨).
        anchor = {"left": "nw", "center": "n", "right": "ne"}.get(a.get("align", "left"), "nw")
        try:
            item = self.canvas.create_text(
                px, py, text=a.get("text", ""), anchor=anchor,
                font=font_spec, fill=a.get("color", DEFAULT_ANNOT_COLOR),
                justify=a.get("align", "left"), angle=angle,
                tags=(f"annot_{a['id']}", "annot"))
        except Exception:
            return
        self._draw_sel_outline_if_needed(a, item)

    def _shape_screen_corners(self, a):
        sx0, sy0 = pdf_to_screen(a["x0"], a["y0"], self._cur_pw, self._cur_ph,
                                  self._cur_rot, self._sc, self._cx, self._cy)
        sx1, sy1 = pdf_to_screen(a["x1"], a["y1"], self._cur_pw, self._cur_ph,
                                  self._cur_rot, self._sc, self._cx, self._cy)
        return sx0, sy0, sx1, sy1

    def _draw_rect_annot(self, a):
        sx0, sy0, sx1, sy1 = self._shape_screen_corners(a)
        lw = max(1, int(round(a.get("line_width", DEFAULT_SHAPE_LINE_WIDTH) * self._sc)))
        fill = a.get("fill_color", DEFAULT_SHAPE_FILL_COLOR) if a.get("fill_enabled") else ""
        item = self.canvas.create_rectangle(
            min(sx0,sx1), min(sy0,sy1), max(sx0,sx1), max(sy0,sy1),
            outline=a.get("line_color", DEFAULT_SHAPE_LINE_COLOR), width=lw, fill=fill,
            tags=(f"annot_{a['id']}", "annot"))
        self._draw_sel_outline_if_needed(a, item)

    def _draw_highlight_annot(self, a):
        sx0, sy0, sx1, sy1 = self._shape_screen_corners(a)
        item = self.canvas.create_rectangle(
            min(sx0,sx1), min(sy0,sy1), max(sx0,sx1), max(sy0,sy1),
            outline="", fill=a.get("fill_color", DEFAULT_HIGHLIGHT_COLOR), stipple="gray50",
            tags=(f"annot_{a['id']}", "annot"))
        self._draw_sel_outline_if_needed(a, item)

    def _draw_arrow_annot(self, a):
        sx0, sy0, sx1, sy1 = self._shape_screen_corners(a)
        lw = max(1, int(round(a.get("line_width", DEFAULT_SHAPE_LINE_WIDTH) * self._sc)))
        item = self.canvas.create_line(
            sx0, sy0, sx1, sy1, fill=a.get("line_color", DEFAULT_SHAPE_LINE_COLOR),
            width=lw, arrow="last", arrowshape=(10,12,4),
            tags=(f"annot_{a['id']}", "annot"))
        self._draw_sel_outline_if_needed(a, item)

    def _draw_sel_outline_if_needed(self, a, item):
        if self.edit_mode and a["id"] == self.selected_id:
            bbox = self.canvas.bbox(item)
            if bbox:
                pad = 4
                self.canvas.create_rectangle(
                    bbox[0]-pad, bbox[1]-pad, bbox[2]+pad, bbox[3]+pad,
                    outline=ACCENT, width=2, dash=(4,2),
                    tags=("annot", "annotsel"))
            if a.get("type") in ("rect", "arrow"):
                self._draw_shape_handles(a)

    def _draw_shape_handles(self, a):
        """선택된 사각형/화살표의 끝점에 마우스로 잡아 크기/방향을 조정할
        수 있는 작은 사각 핸들을 그린다."""
        r = self.HANDLE_R
        for _, (x_pt, y_pt) in self._shape_handle_points(a):
            sx, sy = pdf_to_screen(x_pt, y_pt, self._cur_pw, self._cur_ph,
                                    self._cur_rot, self._sc, self._cx, self._cy)
            self.canvas.create_rectangle(
                sx-r, sy-r, sx+r, sy+r,
                fill=ACCENT, outline="white", width=1,
                tags=("annot", "annotsel"))

    # ── 편집 ────────────────────────────────────────────────
    def _rotate(self, deg):
        """미리보기에서 회전 (부모 그리드도 갱신)"""
        if not self.pages: return
        pg = self.pages[self.idx]
        pg["rot"] = (pg.get("rot", 0) + deg) % 360
        self._show()
        if self.on_change: self.on_change()

    def _delete(self):
        """미리보기에서 현재 페이지 삭제"""
        if not self.pages: return
        if len(self.pages) == 1:
            messagebox.showwarning("경고", "마지막 페이지는 삭제할 수 없습니다.", parent=self)
            return
        if not messagebox.askyesno("삭제 확인",
                f"페이지 {self.idx+1}을 삭제할까요?", parent=self):
            return
        self.pages.pop(self.idx)
        if self.idx >= len(self.pages): self.idx = len(self.pages)-1
        self._show()
        if self.on_change: self.on_change()


# ══════════════════════════════════════════════════════════
#  정리 탭
# ══════════════════════════════════════════════════════════
class OrganizeTab(tk.Frame):
    CW0, CH0 = 158, 228
    TW0, TH0 = 148, 172
    PAD      = 16
    BBAR     = 44
    IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff")

    HOV_BTNS = [
        ("🔍", "preview", 0.15),
        ("↺",  "rotate",  0.38),
        ("⧉",  "dup",     0.62),
        ("🗑", "delete",  0.85),
    ]

    def __init__(self, master):
        super().__init__(master, bg=BG)
        self.pages     = []
        self.checked   = set()
        self.photos    = []
        self.ghost_photos = []   # 드래그 중 마우스를 따라다니는 미리보기용
        self.scale     = 1.0
        self.drag_src  = None
        self.drag_tgt  = None
        self.drag_moved= False
        self.hover_idx = None
        self._rid      = None
        self.status_cb = None   # 상태 표시줄 갱신 콜백 (App 에서 연결)
        self._dirty    = False  # 마지막 내보내기 이후 반영 안 된 변경이 있는지
        self._build()

    def _mark_dirty(self):
        self._dirty = True

    def has_unsaved_changes(self):
        """페이지가 있는데 마지막 내보내기 이후로 변경(추가/삭제/편집/회전 등)이
        있었으면 True — 프로그램 종료 시 확인 질문을 띄울지 판단하는 데 쓴다."""
        return bool(self.pages) and self._dirty

    @property
    def CW(self):     return int(self.CW0   * self.scale)
    @property
    def CH(self):     return int(self.CH0   * self.scale)
    @property
    def TW(self):     return int(self.TW0   * self.scale)
    @property
    def TH(self):     return int(self.TH0   * self.scale)
    @property
    def BBAR_H(self): return int(self.BBAR  * self.scale)

    # ── UI ──────────────────────────────────────────────────
    def _build(self):
        tb = tk.Frame(self, bg=TOOLBAR, pady=8)
        tb.pack(fill="x")

        # ── 파일 그룹 ────────────────────────────────────
        mkbtn(tb, "+ 파일 추가", self._add_files).pack(side="left", padx=(12,6))
        sep_v(tb)

        # ── 선택 그룹 ────────────────────────────────────
        self.chk_var = tk.BooleanVar()
        tk.Checkbutton(tb, variable=self.chk_var, command=self._toggle_all,
                       text="전체선택", bg=TOOLBAR, fg=TEXT, selectcolor=ACCENT,
                       activebackground=TOOLBAR, font=FONT_S,
                       bd=0, highlightthickness=0).pack(side="left", padx=(6,6))
        mkbtn(tb, "선택 삭제", self._delete_checked, bg=DANGER, py=6).pack(side="left", padx=3)
        mkbtn(tb, "전체 삭제", self._clear,           bg=DANGER, py=6).pack(side="left", padx=3)
        sep_v(tb)

        # ── 회전 그룹 ────────────────────────────────────
        mkbtn(tb, "↺ 선택 회전", self._rotate_checked, bg=TOOLBAR,
              fg=TEXT, py=6).pack(side="left", padx=(6,4))

        # ── 내보내기 (오른쪽, 가장 중요한 동작이라 강조) ──
        mkbtn(tb, "▶  내보내기", self._export, bg=ACCENT,
              px=20, py=11).pack(side="right", padx=(4,12))
        sep_v(tb)

        # ── 확대/축소 그룹 (동일 크기 정사각형) ──────────
        mkbtn(tb, "+", lambda: self._zoom(1.18), bg=TOOLBAR, fg=TEXT,
              px=10, py=9, width=2).pack(side="right", padx=2)
        mkbtn(tb, "−", lambda: self._zoom(0.85), bg=TOOLBAR, fg=TEXT,
              px=10, py=9, width=2).pack(side="right", padx=2)
        self.info_lbl = tk.Label(tb, text="", font=FONT_S, bg=TOOLBAR, fg=TEXT_DIM)
        self.info_lbl.pack(side="right", padx=10)

        # ── 파일 영역 (흰 배경 + 옅은 테두리 카드) ────────
        # 안내 문구(제목+설명)는 파일이 없을 때 이 캔버스 위에 직접 그려서
        # (_render 참고) 드롭 영역과 안내 문구 위치가 항상 일치하도록 한다.
        cf = tk.Frame(self, bg=BG)
        cf.pack(fill="both", expand=True, padx=12, pady=(0,12))
        vs = tk.Scrollbar(cf, orient="vertical", bg=TOOLBAR, troughcolor=BG)
        vs.pack(side="right", fill="y")
        self.canvas = tk.Canvas(cf, bg=CARD, bd=0,
                                highlightthickness=1, highlightbackground=BORDER,
                                yscrollcommand=vs.set)
        self.canvas.pack(fill="both", expand=True)
        vs.config(command=self.canvas.yview)

        self.canvas.bind("<Configure>",       lambda e: self._debounce())
        self.canvas.bind("<Motion>",          self._on_hover)
        self.canvas.bind("<Leave>",           self._clear_hover)
        self.canvas.bind("<ButtonPress-1>",   self._on_press)
        self.canvas.bind("<B1-Motion>",       self._on_b1motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self.canvas.bind("<MouseWheel>",
                         lambda e: self.canvas.yview_scroll(-1*(e.delta//120), "units"))
        self.canvas.bind("<Control-MouseWheel>",
                         lambda e: self._zoom(1.1 if e.delta > 0 else 1/1.1))

        if DND_OK:
            for w in (self, self.canvas):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<DragEnter>>", lambda e: self.canvas.config(bg=DROPH))
                w.dnd_bind("<<DragLeave>>", lambda e: self.canvas.config(bg=CARD))
                w.dnd_bind("<<Drop>>",      self._dnd_drop)

        self.after(80, self._render)   # 초기 안내 문구를 캔버스에 바로 그리기

    def _zoom(self, f):
        self.scale = max(0.45, min(2.5, self.scale*f)); self._render()

    # ── 렌더링 ──────────────────────────────────────────────
    def _debounce(self):
        if self._rid: self.after_cancel(self._rid)
        self._rid = self.after(80, self._render)

    def _cols(self):
        return max(1, (max(self.canvas.winfo_width(),1)-self.PAD)//(self.CW+self.PAD))

    def _card_xy(self, idx):
        cols = self._cols()
        return (self.PAD + (idx%cols)*(self.CW+self.PAD),
                self.PAD + (idx//cols)*(self.CH+self.PAD))

    def _render(self, insert_at=None):
        self.canvas.delete("all")
        self.photos.clear()
        n = len(self.pages)

        if n == 0:
            cw = max(self.canvas.winfo_width(), 400)
            ch = max(self.canvas.winfo_height(), 300)
            self.canvas.configure(scrollregion=(0,0,cw,ch))  # 빈 상태에서는 스크롤 불가
            self.canvas.create_text(cw//2, ch//2 - 14,
                text="PDF·이미지 파일을 여기에 드래그하세요",
                font=(FM, 13, "bold"), fill="#6B6B6B", justify="center")
            self.canvas.create_text(cw//2, ch//2 + 16,
                text="여러 파일 추가   ·   드래그로 순서 변경   ·   🔍 버튼으로 미리보기",
                font=FONT_S, fill=TEXT_DIM, justify="center")
            self.info_lbl.config(text="")
            if self.status_cb: self.status_cb(0, 0, 0)
            return

        cols     = self._cols()
        dragging = insert_at is not None and self.drag_src is not None

        if dragging:
            # 드래그 중: 옮기는 카드는 목록에서 빼고, 놓일 자리에 빈 칸을
            # 만들어서 나머지 카드들이 그 칸을 향해 앞뒤로 밀리는 것처럼
            # 보이게 배치한다 (옮기는 카드 자체는 마우스를 따라다니는
            # 미리보기(_draw_ghost)로만 표시).
            order = [i for i in range(n) if i != self.drag_src]
            gap = insert_at - (1 if insert_at > self.drag_src else 0)
            gap = max(0, min(gap, len(order)))
            display = order[:gap] + [None] + order[gap:]
        else:
            display = list(range(n))

        rows    = (len(display)+cols-1)//cols
        total_h = self.PAD + rows*(self.CH+self.PAD)
        cw      = max(self.canvas.winfo_width(), 1)
        self.canvas.configure(scrollregion=(0,0,cw,max(total_h,self.canvas.winfo_height())))

        gap_xy = None
        for slot, pi in enumerate(display):
            x0, y0 = self._card_xy(slot)
            if pi is None:
                gap_xy = (x0, y0)
                continue
            self._draw_card(pi, x0, y0, self.pages[pi])

        if gap_xy is not None:
            x0, y0 = gap_xy
            rr(self.canvas, x0+2, y0+2, x0+self.CW-2, y0+self.CH-2,
               r=12, fill=CARD_CHK, outline="", tags="ins")
            rr(self.canvas, x0, y0, x0+self.CW, y0+self.CH,
               r=14, fill="", outline=ACCENT, width=2, tags="ins")

        if self.hover_idx is not None and self.hover_idx < n:
            self._draw_hover_ol(self.hover_idx)

        nc = len(self.checked)
        self.info_lbl.config(text=f"{n}페이지  |  {nc}개 선택")
        self.chk_var.set(n > 0 and nc == n)
        if self.status_cb:
            nf = len({pg["src"] for pg in self.pages})
            self.status_cb(nf, nc, n)

    # ── 카드 그리기 (글래스 스타일) ─────────────────────────
    def _draw_card(self, idx, x0, y0, pg):
        chk   = pg["id"] in self.checked
        bbar  = self.BBAR_H
        tw, th= self.TW, self.TH
        cx2   = x0 + self.CW//2
        tag   = f"pg_{idx}"
        cbt   = f"cb_{idx}"
        img_h = self.CH - bbar          # 썸네일 영역 높이

        # ── 소프트 그림자 (3겹) ──────────────────────────
        for d, col in [(6,SH1),(4,SH2),(2,"#F2F2F2")]:
            rr(self.canvas, x0+d, y0+d, x0+self.CW+d, y0+self.CH+d,
               r=14, fill=col, outline="", tags=(tag,"shadow"))

        # ── 카드 배경 (둥근 모서리) ─────────────────────
        card_fill = CARD_CHK if chk else CARD
        card_bd   = ACCENT   if chk else BORDER
        rr(self.canvas, x0, y0, x0+self.CW, y0+self.CH,
           r=14, fill=card_fill, outline=card_bd,
           width=2 if chk else 1, tags=(tag,"card"))

        # ── 썸네일 영역 배경 (연한 회색 tint) ────────────
        rr(self.canvas, x0+1, y0+1, x0+self.CW-1, y0+img_h,
           r=14, fill="#F7F7F7", outline="", tags=(tag,"card"))

        # ── 썸네일 이미지 ────────────────────────────────
        pil = pg.get("pil")
        if pil:
            d   = pil.copy()
            rot = pg.get("rot", 0)
            if rot: d = d.rotate(-rot, expand=True)
            pad = 10
            sc  = min((self.CW-pad*2)/d.width, (img_h-pad*2)/d.height)
            nw  = max(1, int(d.width*sc))
            nh  = max(1, int(d.height*sc))
            d   = d.resize((nw, nh), Image.LANCZOS)
            photo = ImageTk.PhotoImage(d)
            self.photos.append(photo)
            icy = y0 + img_h//2
            # 이미지 주변 흰 프레임 + 부드러운 그림자
            self.canvas.create_rectangle(
                cx2-nw//2-2, icy-nh//2-2, cx2+nw//2+2, icy+nh//2+2,
                fill="#DDDDDD", outline="", tags=(tag,"card"))
            self.canvas.create_rectangle(
                cx2-nw//2-1, icy-nh//2-1, cx2+nw//2+1, icy+nh//2+1,
                fill="white", outline="", tags=(tag,"card"))
            self.canvas.create_image(cx2, icy, image=photo, tags=(tag,"card"))
        else:
            self.canvas.create_text(cx2, y0+img_h//2, text="PDF",
                                    font=FONT_B, fill=TEXT_DIM, tags=(tag,"card"))

        # ── 하단 구분선 ─────────────────────────────────
        bar_y = y0 + img_h
        self.canvas.create_line(x0+14, bar_y, x0+self.CW-14, bar_y,
                                fill=BORDER, tags=(tag,"card"))

        # ── 하단 라벨 (파일명 + 페이지번호) ─────────────
        fname = os.path.basename(pg.get("src",""))
        if len(fname) > 17: fname = fname[:14]+"…"
        lcy   = bar_y + bbar//2
        self.canvas.create_text(cx2, lcy-7, text=fname,
                                font=FONT_XS, fill=TEXT_DIM,
                                width=self.CW-14, justify="center", tags=(tag,"card"))
        self.canvas.create_text(cx2, lcy+8, text=f"{pg['pidx']+1}",
                                font=(FM,9,"bold"), fill=ACCENT, tags=(tag,"card"))

        # ── 체크박스 (좌상단) ────────────────────────────
        cbx, cby, r = x0+15, y0+15, 9
        if chk:
            self.canvas.create_oval(cbx-r,cby-r,cbx+r,cby+r,
                fill=ACCENT, outline="white", width=2, tags=(tag,cbt,"cb"))
            self.canvas.create_text(cbx,cby, text="✓",
                font=(FM,10,"bold"), fill="white", tags=(tag,cbt,"cb"))
        else:
            self.canvas.create_oval(cbx-r,cby-r,cbx+r,cby+r,
                fill="white", outline="#C9C9C9", width=1.5, tags=(tag,cbt,"cb"))

    # ── 호버 오버레이 ────────────────────────────────────────
    def _draw_hover_ol(self, idx):
        if idx >= len(self.pages): return
        x0, y0 = self._card_xy(idx)
        bbar   = self.BBAR_H
        bar_y  = y0 + self.CH - bbar

        # 메인 컬러 테두리 (카드 전체)
        rr(self.canvas, x0-3, y0-3, x0+self.CW+3, y0+self.CH+3,
           r=16, fill="", outline=ACCENT, width=3, tags="hov")

        # 하단 바 강조
        rr(self.canvas, x0+1, bar_y+1, x0+self.CW-1, y0+self.CH-1,
           r=0, fill=ACCENT, outline="", tags="hov")
        # 아래 모서리만 둥글게
        rr(self.canvas, x0+1, bar_y+1, x0+self.CW-1, y0+self.CH-1,
           r=13, fill=ACCENT, outline="", tags="hov")

        # 버튼 그리기  ← tag_bind 없이 _on_press 에서만 처리
        by = bar_y + bbar//2
        r  = min(13, bbar//2 - 4)
        btn_styles = {
            "preview": ("#ffffff",  ACCENT,   ACCENT),
            "rotate":  (CARD_CHK,   ACCENT_L, ACCENT),
            "dup":     ("#ffffff",  ACCENT_D, ACCENT_D),
            "delete":  (DANGER,    "#ff8070", "white"),
        }
        for icon, key, rx in self.HOV_BTNS:
            bx   = x0 + int(self.CW * rx)
            bf, bo, fi = btn_styles.get(key, ("#fff", ACCENT, ACCENT))
            htag = f"ha_{key}_{idx}"
            self.canvas.create_oval(bx-r, by-r, bx+r, by+r,
                fill=bf, outline=bo, width=2, tags=("hov", htag))
            self.canvas.create_text(bx, by, text=icon,
                font=("Segoe UI Emoji", 13), fill=fi, tags=("hov", htag))
            # ※ tag_bind 제거 → _on_press 에서 단독 처리 (이중 실행 방지)

    def _clear_hover(self, _=None):
        self.canvas.delete("hov"); self.hover_idx = None
        if self.drag_src is None:
            self.canvas.config(cursor="")

    def _on_hover(self, event):
        if self.drag_src is not None: return
        cx  = self.canvas.canvasx(event.x)
        cy  = self.canvas.canvasy(event.y)
        idx = self._xy_to_card(cx, cy)
        if idx != self.hover_idx:
            self.canvas.delete("hov")
            self.hover_idx = idx
            if idx is not None: self._draw_hover_ol(idx)

        # 🔍/↺/⧉/🗑 같은 작은 액션 버튼 위에서는 클릭 가능함을 보여주는
        # 손가락 커서로, 카드 본체 위에서는 "이동 가능" 커서로 구분한다.
        on_button = False
        for item in self.canvas.find_overlapping(cx-4, cy-4, cx+4, cy+4):
            if any(t.startswith("ha_") for t in self.canvas.gettags(item)):
                on_button = True
                break
        if on_button:
            self.canvas.config(cursor="hand2")
        else:
            self.canvas.config(cursor="fleur" if idx is not None else "")

    # ── 캔버스 이벤트 ────────────────────────────────────────
    def _on_press(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        # ① 호버 액션 버튼 (ha_*) — 가장 먼저 확인
        for item in self.canvas.find_overlapping(cx-4, cy-4, cx+4, cy+4):
            for t in self.canvas.gettags(item):
                if t.startswith("ha_"):
                    parts = t.split("_")
                    self._hov_action(parts[1], int(parts[2]))
                    return   # 여기서 반드시 종료 → 이중 실행 방지

        # ② 체크박스 (cb_*)
        for item in self.canvas.find_overlapping(cx-4, cy-4, cx+4, cy+4):
            for t in self.canvas.gettags(item):
                if t.startswith("cb_"):
                    pid = self.pages[int(t.split("_")[1])]["id"]
                    self.checked ^= {pid}
                    self._render(); return

        # ③ 카드 본체 → 드래그 준비
        idx = self._xy_to_card(cx, cy)
        if idx is not None:
            self.drag_src   = idx
            self.drag_tgt   = None
            self.drag_moved = False

    def _on_b1motion(self, event):
        if self.drag_src is None: return
        self.canvas.delete("hov"); self.hover_idx = None
        if not self.drag_moved:
            self.canvas.config(cursor="fleur")   # 드래그가 실제로 시작될 때 커서 전환
        self.drag_moved = True
        cx  = self.canvas.canvasx(event.x)
        cy  = self.canvas.canvasy(event.y)
        tgt = self._xy_to_insert(cx, cy)
        if tgt != self.drag_tgt:
            self.drag_tgt = tgt; self._render(insert_at=tgt)   # 격자 재배치는 목표 칸이 바뀔 때만 (부드러움 유지)
        self._draw_ghost(cx, cy)   # 카드 미리보기는 매 프레임 마우스를 그대로 따라감
        h = self.canvas.winfo_height()
        if event.y < 50:     self.canvas.yview_scroll(-1,"units")
        elif event.y > h-50: self.canvas.yview_scroll( 1,"units")

    def _draw_ghost(self, cx, cy):
        """드래그 중인 카드를 마우스 위치에 작게 띄워 '들고 있는' 느낌을 준다."""
        self.canvas.delete("ghost")
        self.ghost_photos.clear()
        if self.drag_src is None or self.drag_src >= len(self.pages): return
        pg = self.pages[self.drag_src]
        gw, gh = int(self.CW*0.72), int(self.CH*0.72)
        x0, y0 = cx-gw//2, cy-gh//2
        for d, col in [(6,SH1),(3,SH2)]:
            rr(self.canvas, x0+d, y0+d, x0+gw+d, y0+gh+d,
               r=12, fill=col, outline="", tags="ghost")
        rr(self.canvas, x0, y0, x0+gw, y0+gh,
           r=12, fill=CARD, outline=ACCENT, width=2, tags="ghost")
        pil = pg.get("pil")
        if pil:
            d   = pil.copy()
            rot = pg.get("rot", 0)
            if rot: d = d.rotate(-rot, expand=True)
            pad = 8
            sc  = min((gw-pad*2)/d.width, (gh-pad*2)/d.height)
            nw, nh = max(1,int(d.width*sc)), max(1,int(d.height*sc))
            d = d.resize((nw, nh), Image.LANCZOS)
            photo = ImageTk.PhotoImage(d)
            self.ghost_photos.append(photo)
            self.canvas.create_image(cx, cy, image=photo, tags="ghost")
        else:
            self.canvas.create_text(cx, cy, text="PDF", font=FONT_B,
                                    fill=TEXT_DIM, tags="ghost")

    def _on_release(self, event):
        if self.drag_src is None: return
        if self.drag_moved and self.drag_tgt is not None:
            src, tgt = self.drag_src, self.drag_tgt
            if tgt > src: tgt -= 1
            if src != tgt:
                pg = self.pages.pop(src); self.pages.insert(tgt, pg)
                self._mark_dirty()
        # 단순 클릭은 아무 동작 없음 (미리보기는 🔍 버튼 또는 더블클릭으로)
        self.drag_src = self.drag_tgt = None
        self.drag_moved = False
        self.canvas.config(cursor="")
        self._render()

    def _on_double_click(self, event):
        """카드를 더블클릭하면 🔍 버튼과 동일하게 미리보기를 연다."""
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        for item in self.canvas.find_overlapping(cx-4, cy-4, cx+4, cy+4):
            for t in self.canvas.gettags(item):
                if t.startswith("ha_") or t.startswith("cb_"):
                    return   # 액션 버튼/체크박스 위에서는 그쪽 단일클릭 동작만 수행
        idx = self._xy_to_card(cx, cy)
        if idx is not None:
            self._open_preview(idx)

    # ── 좌표 변환 ───────────────────────────────────────────
    def _xy_to_card(self, cx, cy):
        cols = self._cols()
        col  = int((cx-self.PAD)//(self.CW+self.PAD))
        row  = int((cy-self.PAD)//(self.CH+self.PAD))
        if not (0 <= col < cols): return None
        idx = row*cols+col
        if not (0 <= idx < len(self.pages)): return None
        x0, y0 = self._card_xy(idx)
        return idx if (x0<=cx<=x0+self.CW and y0<=cy<=y0+self.CH) else None

    def _xy_to_insert(self, cx, cy):
        cols = self._cols()
        col  = int((cx-self.PAD/2)//(self.CW+self.PAD))
        row  = int((cy-self.PAD/2)//(self.CH+self.PAD))
        col  = max(0, min(col, cols-1))
        idx  = row*cols+col
        x0, _ = self._card_xy(idx) if idx < len(self.pages) else (0,0)
        if cx > x0+self.CW/2: idx += 1
        return max(0, min(idx, len(self.pages)))

    # ── 호버 액션 ───────────────────────────────────────────
    def _hov_action(self, key, idx):
        if not (0 <= idx < len(self.pages)): return
        if   key == "preview": self._open_preview(idx)
        elif key == "rotate":
            self.pages[idx]["rot"] = (self.pages[idx].get("rot",0)+90)%360
            self._mark_dirty()
            self._render()
        elif key == "dup":
            pg = dict(self.pages[idx]); pg["id"] = next(_id_gen)
            # annots 는 리스트(가변 객체)이므로 얕은 복사(dict())만 하면
            # 원본과 복제본이 같은 리스트를 공유하게 된다 — 반드시 새 리스트로
            # 깊은 복사해서 이후 편집이 서로 독립적이도록 한다.
            pg["annots"] = [dict(a) for a in pg.get("annots", [])]
            self.pages.insert(idx+1, pg)
            self._mark_dirty()
            self._render()
        elif key == "delete":
            self.pages.pop(idx)
            self.hover_idx = None
            self._mark_dirty()
            self._render()

    # ── 체크박스 전체선택 / 삭제 / 회전 ────────────────────
    def _toggle_all(self):
        if self.chk_var.get(): self.checked = {pg["id"] for pg in self.pages}
        else: self.checked.clear()
        self._render()

    def _delete_checked(self):
        if not self.checked:
            messagebox.showinfo("알림","삭제할 페이지를 선택하세요."); return
        self.pages = [pg for pg in self.pages if pg["id"] not in self.checked]
        self.checked.clear()
        self._mark_dirty()
        self._render()

    def _rotate_checked(self):
        tgt = self.checked or {pg["id"] for pg in self.pages}
        for pg in self.pages:
            if pg["id"] in tgt: pg["rot"]=(pg.get("rot",0)+90)%360
        self._mark_dirty()
        self._render()

    # ── 파일 관리 ────────────────────────────────────────────
    def _add_files(self):
        ps = filedialog.askopenfilenames(title="PDF/이미지 파일 선택",
                                         filetypes=[("PDF/이미지", "*.pdf *.jpg *.jpeg *.png *.bmp *.webp *.tiff"),
                                                    ("PDF", "*.pdf"),
                                                    ("이미지", "*.jpg *.jpeg *.png *.bmp *.webp *.tiff")])
        self._load_pdfs(list(ps))

    def _dnd_drop(self, event):
        self.canvas.config(bg=CARD)
        self._load_pdfs([p for p in parse_paths(event.data)
                         if p.lower().endswith(".pdf") or p.lower().endswith(self.IMG_EXTS)])

    def _image_to_temp_pdf(self, img_path):
        """이미지 한 장을 임시 PDF 파일로 변환해서 그 경로를 반환한다.
        이후 파이프라인(정리/편집/내보내기)은 원래 PDF와 완전히 동일하게
        다룬다. 이미지를 72dpi(1px=1pt) 그대로 열면 페이지 크기가 mm로
        비상식적으로 커지므로(예: 3000px 폭 사진이 1m 폭 페이지가 됨),
        적당한 해상도(150dpi) 기준으로 페이지 크기를 다시 잡는다."""
        if not PREVIEW_OK:
            messagebox.showerror("오류", "이미지 불러오기에는 pymupdf(fitz)가 필요합니다.")
            return None
        try:
            # 휴대폰 사진 등은 실제 픽셀은 그대로 두고 EXIF Orientation
            # 태그로만 "보여줄 때 이렇게 돌려라" 라고 표시하는 경우가
            # 많다. fitz.insert_image() 는 이 태그를 무시하고 원본 픽셀을
            # 그대로 삽입해버려서 사진이 옆으로 눕는 문제가 있었다 — PIL로
            # 열어 exif_transpose() 로 방향을 실제 픽셀에 반영한 뒤 그
            # 보정된 이미지를 페이지에 넣는다.
            pil_img = Image.open(img_path)
            pil_img = ImageOps.exif_transpose(pil_img)
            if pil_img.mode not in ("RGB", "L"):
                pil_img = pil_img.convert("RGB")
            px_w, px_h = pil_img.size
            target_dpi = 150.0
            pt_w, pt_h = px_w/target_dpi*72.0, px_h/target_dpi*72.0

            tmp_dir = tempfile.mkdtemp(prefix="pdftool_img_")
            base = os.path.splitext(os.path.basename(img_path))[0]
            corrected_path = os.path.join(tmp_dir, f"_src_{base}.png")
            pil_img.save(corrected_path)

            doc = fitz.open()
            page = doc.new_page(width=pt_w, height=pt_h)
            page.insert_image(fitz.Rect(0, 0, pt_w, pt_h), filename=corrected_path)

            tmp_path = os.path.join(tmp_dir, f"{base}.pdf")
            doc.save(tmp_path)
            doc.close()
            return tmp_path
        except Exception as e:
            messagebox.showerror("오류", f"이미지를 불러오지 못했습니다.\n{os.path.basename(img_path)}\n{e}")
            return None

    def _load_pdfs(self, paths):
        n_before = len(self.pages)
        for path in paths:
            try:
                src_image_ext = None
                if path.lower().endswith(self.IMG_EXTS):
                    src_image_ext = os.path.splitext(path)[1].lower()
                    converted = self._image_to_temp_pdf(path)
                    if converted is None: continue
                    path = converted
                r = PdfReader(path)
                # 페이지 pt 크기는 회전 편집(rot)과 무관한 "원본" 크기여야
                # 하므로, 미리보기 렌더링과 동일한 출처(fitz page.rect)에서
                # 가져와 일관성을 유지한다.
                fdoc = fitz.open(path) if PREVIEW_OK else None
                for pidx in range(len(r.pages)):
                    pil = make_thumb(path, pidx, self.TW0, self.TH0)
                    if fdoc is not None:
                        frect = fdoc[pidx].rect
                        pw_pt, ph_pt = frect.width, frect.height
                    else:
                        mb = r.pages[pidx].mediabox
                        pw_pt, ph_pt = float(mb.width), float(mb.height)
                    self.pages.append({"id":next(_id_gen),"src":path,
                                       "pidx":pidx,"pil":pil,"rot":0,
                                       "page_w_pt":pw_pt,"page_h_pt":ph_pt,
                                       "annots":[], "src_image_ext":src_image_ext})
                if fdoc is not None: fdoc.close()
            except Exception as e:
                messagebox.showerror("오류",f"{os.path.basename(path)}\n{e}")
        if len(self.pages) != n_before:
            self._mark_dirty()
        self._render()

    def _clear(self):
        self.pages.clear(); self.checked.clear()
        self.photos.clear(); self.hover_idx = None; self._render()

    def _open_preview(self, idx):
        if not self.pages: return
        PreviewWin(self.winfo_toplevel(), self.pages, idx,
                   on_change=self._on_preview_change)   # 편집 후 그리드 자동 갱신

    def _on_preview_change(self):
        """미리보기에서 텍스트/도형을 추가·수정해도 정리 탭 카드
        썸네일에는 반영되지 않던 문제 수정 — 내보내기와 같은 굽기
        로직으로 썸네일을 다시 만들어 캐시를 갱신한다."""
        self._mark_dirty()
        for pg in self.pages:
            thumb = make_thumb_for_page(pg, self.TW0, self.TH0)
            if thumb is not None:
                pg["pil"] = thumb
        self._render()

    # ── 내보내기 ────────────────────────────────────────────
    def _export(self):
        if not self.pages:
            messagebox.showwarning("경고","페이지가 없습니다."); return
        init_dir = os.path.dirname(self.pages[0]["src"]) if self.pages else ""

        # 사진 한 장만 불러와서 작업한 경우, 저장 형식도 그 사진과 같은
        # 걸(jpg/png) 기본값으로 제안한다 — PDF만 고집할 이유가 없어서.
        default_ext = ".pdf"
        if len(self.pages) == 1:
            img_ext = self.pages[0].get("src_image_ext")
            if img_ext in (".jpg", ".jpeg"):
                default_ext = ".jpg"
            elif img_ext == ".png":
                default_ext = ".png"
        filetypes = [("PDF","*.pdf"), ("JPG 이미지","*.jpg"), ("PNG 이미지","*.png")]
        default_label = {".pdf":"PDF", ".jpg":"JPG 이미지", ".png":"PNG 이미지"}[default_ext]
        filetypes.sort(key=lambda ft: ft[0] != default_label)   # 기본 형식을 맨 앞으로

        out = filedialog.asksaveasfilename(title="저장",
            defaultextension=default_ext, filetypes=filetypes,
            initialdir=init_dir, initialfile=f"output{default_ext}")
        if not out: return
        ext = os.path.splitext(out)[1].lower()
        try:
            if ext in (".jpg", ".jpeg", ".png"):
                if not PREVIEW_OK:
                    messagebox.showerror("오류", "이미지로 저장하려면 pymupdf(fitz)가 필요합니다.")
                    return
                saved = self._export_as_images(out, ext)
                self._dirty = False
                if len(saved) == 1:
                    messagebox.showinfo("완료", f"저장 완료!\n{saved[0]}")
                else:
                    messagebox.showinfo("완료",
                        f"페이지마다 별도 파일로 {len(saved)}개 저장 완료!\n{os.path.dirname(saved[0])}")
            elif PREVIEW_OK:
                self._export_with_fitz(out)
                self._dirty = False
                messagebox.showinfo("완료", f"저장 완료!\n{out}")
            else:
                self._export_with_pypdf(out)
                self._dirty = False
                messagebox.showinfo("완료", f"저장 완료!\n{out}")
        except Exception as e:
            messagebox.showerror("오류",str(e))

    def _export_with_pypdf(self, out):
        """PyMuPDF(fitz) 를 못 쓰는 환경용 대체 경로. 텍스트 annot 을
        구울 수단이 없으므로(편집 자체가 fitz 없이는 불가능해 이 경우
        annots 는 항상 비어 있다) 페이지 복사 + 회전만 처리한다."""
        w     = PdfWriter()
        cache = {}
        for pg in self.pages:
            src = pg["src"]
            if src not in cache: cache[src] = PdfReader(src)
            page  = cache[src].pages[pg["pidx"]]
            added = w.add_page(page)   # 원본과 독립된 클론 객체 반환
            rot   = pg.get("rot",0)
            if rot: added.rotate(rot)
        with open(out,"wb") as f: w.write(f)

    def _build_baked_doc(self):
        """모든 페이지를 복사하고, 우리 앱에서 추가한 회전(pg["rot"])과
        텍스트/도형 annot 을 실제 콘텐츠로 구운 fitz.Document 를 새로
        만들어 반환한다(호출자가 닫아야 함). 소스 문서를 직접 수정하지
        않고(페이지 복제 시 같은 원본을 공유할 수 있으므로) out_doc 에
        복사해 넣은 뒤 그 복사본에만 그린다. PDF 저장과 이미지 저장이
        이 결과물을 공유해서 둘의 결과가 어긋나지 않게 한다."""
        out_doc    = fitz.open()
        src_cache  = {}
        font_cache = {}
        try:
            for pg in self.pages:
                src = pg["src"]
                if src not in src_cache: src_cache[src] = fitz.open(src)
                src_doc    = src_cache[src]
                pidx       = pg["pidx"]
                native_rot = src_doc[pidx].rotation

                out_doc.insert_pdf(src_doc, from_page=pidx, to_page=pidx)
                out_page  = out_doc[-1]
                extra_rot = pg.get("rot", 0)
                if extra_rot:
                    out_page.set_rotation((native_rot + extra_rot) % 360)

                _bake_all_annots(out_page, pg, native_rot, font_cache)
            return out_doc
        finally:
            for d in src_cache.values(): d.close()

    def _export_with_fitz(self, out):
        out_doc = self._build_baked_doc()
        try:
            out_doc.save(out)
        finally:
            out_doc.close()

    def _export_as_images(self, out, ext):
        """확장자가 jpg/png 일 때: 페이지가 1장이면 고른 경로에 그대로,
        여러 장이면 같은 폴더에 '_p1','_p2'... 를 붙여 각각 저장한다
        (PDF 한 장이 이미지 한 장이 되는 형식적 제약 때문)."""
        fmt = "JPEG" if ext in (".jpg", ".jpeg") else "PNG"
        out_doc = self._build_baked_doc()
        try:
            base_dir  = os.path.dirname(out)
            base_name = os.path.splitext(os.path.basename(out))[0]
            dpi = 300
            sc  = dpi / 72
            n   = len(out_doc)
            saved = []
            for i, page in enumerate(out_doc):
                pix = page.get_pixmap(matrix=fitz.Matrix(sc, sc), alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                path = out if n == 1 else os.path.join(base_dir, f"{base_name}_p{i+1:03d}{ext}")
                if fmt == "JPEG":
                    img.save(path, "JPEG", quality=92)
                else:
                    img.save(path, "PNG")
                saved.append(path)
            return saved
        finally:
            out_doc.close()


# ══════════════════════════════════════════════════════════
#  변환 탭  —  통합 드롭존  (PDF→이미지 / 이미지→PDF 자동 감지)
# ══════════════════════════════════════════════════════════
class ConvertTab(tk.Frame):
    IMG_EXTS = (".jpg",".jpeg",".png",".bmp",".webp",".tiff")
    ICW, ICH, IPAD = 118, 148, 10

    def __init__(self, master):
        super().__init__(master, bg=BG)
        self.mode           = None        # None | "pdf2img" | "img2pdf"
        self.pdf_path_str   = ""
        self.pdf_thumbs     = []          # PIL (PDF 페이지)
        self.img_files      = []
        self.img_thumbs     = []          # PIL (이미지 파일)
        self.img_photos     = []          # PhotoImage 레퍼런스
        self.img_ghost_photos = []        # 드래그 중 마우스를 따라다니는 미리보기용
        self.img_hover      = None
        self.img_drag_src   = None
        self.img_drag_tgt   = None
        self.img_drag_moved = False
        self.out_name       = tk.StringVar(value="")
        self.status_cb      = None   # 상태 표시줄 갱신 콜백 (App 에서 연결)
        self._build()

    # ── UI 구성 ─────────────────────────────────────────────
    def _build(self):
        tk.Label(self, text="파일 변환", font=FONT_H, bg=BG, fg=TEXT).pack(pady=(18,4))
        tk.Label(self, text="PDF를 넣으면 → 이미지로  |  이미지를 넣으면 → PDF로  자동 변환",
                 font=FONT, bg=BG, fg=TEXT_DIM).pack(pady=(0,8))

        # ── 드롭존 ──────────────────────────────────────────
        self.dz = tk.Frame(self, bg=BG, bd=2, relief="solid",
                           highlightthickness=2, highlightbackground=BORDER, cursor="hand2")
        self.dz.pack(fill="x", padx=20, pady=(0,6))
        self.dz_icon = tk.Label(self.dz, text="📂",
                                font=("Segoe UI Emoji",28), bg=BG, fg=TEXT_DIM, cursor="hand2")
        self.dz_icon.pack(pady=(12,2))
        self.dz_lbl  = tk.Label(self.dz,
                                text="PDF 또는 이미지(JPG·PNG·BMP·WEBP)를 끌어다 놓거나 클릭",
                                font=FONT_S, bg=BG, fg=TEXT_DIM, cursor="hand2")
        self.dz_lbl.pack(pady=(0,10))
        for w in (self.dz, self.dz_icon, self.dz_lbl):
            w.bind("<Button-1>", lambda e: self._pick_files())
            if DND_OK:
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<DragEnter>>", lambda e: self._dz_hl(True))
                w.dnd_bind("<<DragLeave>>", lambda e: self._dz_hl(False))
                w.dnd_bind("<<Drop>>",      self._on_drop)

        # ── 상태 바 ─────────────────────────────────────────
        sb = tk.Frame(self, bg=BG); sb.pack(fill="x", padx=20, pady=(0,4))
        self.status_lbl = tk.Label(sb, text="", font=FONT_B, bg=BG, fg=ACCENT)
        self.status_lbl.pack(side="left")
        self.reset_btn = mkbtn(sb, "✕ 초기화", self._reset, bg=DANGER, px=8, py=3)

        # ── 미리보기 캔버스 (흰 배경 + 옅은 테두리 카드) ─────
        cf = tk.Frame(self, bg=BG); cf.pack(fill="both", expand=True, padx=20, pady=(0,12))
        pvs = tk.Scrollbar(cf, orient="vertical", bg=TOOLBAR, troughcolor=BG)
        pvs.pack(side="right", fill="y")
        self.pcanvas = tk.Canvas(cf, bg=CARD, bd=0,
                                 highlightthickness=1, highlightbackground=BORDER,
                                 yscrollcommand=pvs.set)
        self.pcanvas.pack(fill="both", expand=True)
        pvs.config(command=self.pcanvas.yview)
        self.pcanvas.bind("<Configure>",       lambda e: self._render_preview())
        self.pcanvas.bind("<Motion>",          self._img_on_hover)
        self.pcanvas.bind("<Leave>",           self._img_clear_hover)
        self.pcanvas.bind("<ButtonPress-1>",   self._img_on_press)
        self.pcanvas.bind("<B1-Motion>",       self._img_on_b1motion)
        self.pcanvas.bind("<ButtonRelease-1>", self._img_on_release)
        self.pcanvas.bind("<MouseWheel>",
            lambda e: self.pcanvas.yview_scroll(-1*(e.delta//120), "units"))

        # ── 하단 컨트롤 ─────────────────────────────────────
        bot = tk.Frame(self, bg=PANEL); bot.pack(fill="x", side="bottom")
        tk.Frame(bot, bg=BORDER, height=1).pack(fill="x")
        inner = tk.Frame(bot, bg=PANEL); inner.pack(padx=20, pady=8)

        # 파일명 (자동 채워지고 직접 수정도 가능)
        fn_row = tk.Frame(inner, bg=PANEL); fn_row.pack(fill="x", pady=(0,6))
        tk.Label(fn_row, text="저장 파일명:", font=FONT_S, bg=PANEL, fg=TEXT_DIM).pack(side="left")
        self.name_entry = tk.Entry(fn_row, textvariable=self.out_name, font=FONT_B,
                                   bg=BG, fg=TEXT, relief="solid", bd=1, width=24,
                                   insertbackground=ACCENT)
        self.name_entry.pack(side="left", padx=(6,2))
        self.ext_lbl = tk.Label(fn_row, text="", font=FONT_B, bg=PANEL, fg=ACCENT)
        self.ext_lbl.pack(side="left")

        # 저장 버튼 (가장 중요한 동작이라 강조)
        self.dl_btn = mkbtn(inner, "▼  저장하기", self._do_save, px=36, py=12)
        self.dl_btn.pack(pady=(4,2))

        self._reset()

    # ── 상태 표시줄 갱신 (기존 status_lbl 텍스트를 그대로 전달) ──
    def _set_status(self, text):
        self.status_lbl.config(text=text)
        if self.status_cb: self.status_cb(text)

    # ── 드롭존 ──────────────────────────────────────────────
    def _dz_hl(self, on):
        col = DROPH if on else BG
        for w in (self.dz, self.dz_icon, self.dz_lbl):
            w.config(bg=col)

    def _pick_files(self):
        ps = list(filedialog.askopenfilenames(
            title="파일 선택",
            filetypes=[
                ("지원 파일", "*.pdf *.jpg *.jpeg *.png *.bmp *.webp *.tiff"),
                ("PDF", "*.pdf"),
                ("이미지", "*.jpg *.jpeg *.png *.bmp *.webp *.tiff"),
            ]))
        if ps: self._load_files(ps)

    def _on_drop(self, event):
        self._dz_hl(False)
        self._load_files(parse_paths(event.data))

    def _load_files(self, paths):
        pdfs = [p for p in paths if p.lower().endswith(".pdf")]
        imgs = [p for p in paths if any(p.lower().endswith(e) for e in self.IMG_EXTS)]
        if self.mode is None:
            if pdfs and not imgs:
                self._set_mode_pdf(pdfs[0])
            elif imgs:
                self._set_mode_img(imgs)
        elif self.mode == "img2pdf":
            if imgs:
                self._add_imgs(imgs)
            elif pdfs:
                messagebox.showinfo("알림", "이미지 모드입니다.\n초기화 후 PDF를 넣어주세요.")
        elif self.mode == "pdf2img":
            if pdfs:
                self._set_mode_pdf(pdfs[0])
            elif imgs:
                messagebox.showinfo("알림", "PDF 모드입니다.\n초기화 후 이미지를 넣어주세요.")

    # ── 모드 설정 ────────────────────────────────────────────
    def _set_mode_pdf(self, path):
        try:
            n = len(PdfReader(path).pages)
        except Exception as e:
            messagebox.showerror("오류", str(e)); return
        self.mode           = "pdf2img"
        self.pdf_path_str   = path
        self.pdf_thumbs     = []
        for i in range(n):
            self.pdf_thumbs.append(make_thumb(path, i, 148, 172))
            if i % 5 == 0: self.update()
        base = os.path.splitext(os.path.basename(path))[0]
        self.out_name.set(base)
        self.ext_lbl.config(text=".png")
        self._set_status(f"📄  PDF  ·  {n}페이지  →  PNG 이미지로 변환 (최고 화질)")
        self.reset_btn.pack(side="right")
        self.dl_btn.config(state="normal", bg=ACCENT)
        self._render_preview()

    def _set_mode_img(self, paths):
        self.mode = "img2pdf"
        self._add_imgs(paths)

    def _add_imgs(self, paths):
        for p in paths:
            if p not in self.img_files:
                self.img_files.append(p)
                thumb = None
                if PREVIEW_OK:
                    try:
                        pil = Image.open(p)
                        pil.thumbnail((200, 200), Image.LANCZOS)
                        thumb = pil.copy()
                    except Exception:
                        pass
                self.img_thumbs.append(thumb)
        if self.img_files:
            n = len(self.img_files)
            # 첫 번째 이미지 파일명을 기본값으로 (비어있을 때만)
            if not self.out_name.get():
                base = os.path.splitext(os.path.basename(self.img_files[0]))[0]
                self.out_name.set(base)
            self.ext_lbl.config(text=".pdf")
            self._set_status(f"🖼  이미지  ·  {n}개  →  PDF로 변환")
            self.reset_btn.pack(side="right")
            self.dl_btn.config(state="normal", bg=ACCENT)
            self._render_preview()

    def _reset(self):
        self.mode = None
        self.pdf_path_str = ""
        self.pdf_thumbs.clear()
        self.img_files.clear()
        self.img_thumbs.clear()
        self.img_photos.clear()
        self.img_hover = None
        self.out_name.set("")
        self.ext_lbl.config(text="")
        self._set_status("")
        self.reset_btn.pack_forget()
        self.dl_btn.config(state="disabled", bg="#CCCCCC")
        self.pcanvas.delete("all")
        self.pcanvas.after(80, self._draw_hint)

    def _draw_hint(self):
        self.pcanvas.delete("all")
        cw = max(self.pcanvas.winfo_width(), 200)
        ch = max(self.pcanvas.winfo_height(), 100)
        self.pcanvas.configure(scrollregion=(0,0,cw,ch))  # 빈 상태에서는 스크롤 불가
        self.pcanvas.create_text(cw//2, ch//2,
            text="PDF 또는 이미지를 위 드롭존에 넣으세요",
            font=FONT, fill=TEXT_DIM, justify="center")

    # ── 미리보기 렌더링 ──────────────────────────────────────
    def _img_cols(self):
        return max(1, (max(self.pcanvas.winfo_width(),1)-self.IPAD)//(self.ICW+self.IPAD))

    def _img_card_xy(self, idx):
        cols = self._img_cols()
        return (self.IPAD + (idx%cols)*(self.ICW+self.IPAD),
                self.IPAD + (idx//cols)*(self.ICH+self.IPAD))

    def _render_preview(self, insert_at=None):
        self.pcanvas.delete("all")
        self.img_photos.clear()
        if self.mode is None:
            self._draw_hint(); return
        if self.mode == "pdf2img":
            items  = self.pdf_thumbs
            labels = [f"p.{i+1}" for i in range(len(self.pdf_thumbs))]
        else:
            items  = self.img_thumbs
            labels = [os.path.basename(p) for p in self.img_files]
        n = len(items)
        if n == 0: self._draw_hint(); return
        cols     = self._img_cols()
        dragging = (self.mode == "img2pdf" and insert_at is not None
                    and self.img_drag_src is not None)

        if dragging:
            # 옮기는 이미지는 목록에서 빼고 놓일 자리에 빈 칸을 만들어
            # 나머지 카드들이 밀리는 것처럼 보이게 배치 (정리 탭과 동일)
            order = [i for i in range(n) if i != self.img_drag_src]
            gap = insert_at - (1 if insert_at > self.img_drag_src else 0)
            gap = max(0, min(gap, len(order)))
            display = order[:gap] + [None] + order[gap:]
        else:
            display = list(range(n))

        rows    = (len(display)+cols-1)//cols
        total_h = self.IPAD + rows*(self.ICH+self.IPAD)
        cw      = max(self.pcanvas.winfo_width(), 1)
        self.pcanvas.configure(
            scrollregion=(0,0,cw,max(total_h,self.pcanvas.winfo_height())))

        gap_xy = None
        for slot, pi in enumerate(display):
            x0, y0 = self._img_card_xy(slot)
            if pi is None:
                gap_xy = (x0, y0)
                continue
            self._draw_card(pi, x0, y0, items[pi], labels[pi])

        if gap_xy is not None:
            x0, y0 = gap_xy
            rr(self.pcanvas, x0+2, y0+2, x0+self.ICW-2, y0+self.ICH-2,
               r=10, fill=CARD_CHK, outline="", tags="iins")
            rr(self.pcanvas, x0, y0, x0+self.ICW, y0+self.ICH,
               r=12, fill="", outline=ACCENT, width=2, tags="iins")

        if self.img_hover is not None and self.img_hover < n:
            self._draw_hover(self.img_hover)

    def _draw_card(self, idx, x0, y0, thumb, label):
        tag = f"ic_{idx}"
        lby = y0 + self.ICH - 44
        cx2 = x0 + self.ICW//2
        for d, col in [(5,SH1),(3,SH2)]:
            rr(self.pcanvas, x0+d, y0+d, x0+self.ICW+d, y0+self.ICH+d,
               r=12, fill=col, outline="", tags=(tag,"shadow"))
        rr(self.pcanvas, x0, y0, x0+self.ICW, y0+self.ICH,
           r=12, fill=CARD, outline=BORDER, width=1, tags=(tag,"card"))
        rr(self.pcanvas, x0+1, y0+1, x0+self.ICW-1, y0+lby,
           r=12, fill="#F7F7F7", outline="", tags=(tag,"card"))
        if PREVIEW_OK and thumb:
            sc  = min((self.ICW-16)/thumb.width, (lby-y0-16)/thumb.height)
            nw  = max(1, int(thumb.width*sc))
            nh  = max(1, int(thumb.height*sc))
            img = thumb.resize((nw, nh), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.img_photos.append(photo)
            icy = y0+(lby-y0)//2
            self.pcanvas.create_rectangle(cx2-nw//2-2,icy-nh//2-2,cx2+nw//2+2,icy+nh//2+2,
                fill="#DDDDDD", outline="", tags=(tag,"card"))
            self.pcanvas.create_rectangle(cx2-nw//2-1,icy-nh//2-1,cx2+nw//2+1,icy+nh//2+1,
                fill="white", outline="", tags=(tag,"card"))
            self.pcanvas.create_image(cx2, icy, image=photo, tags=(tag,"card"))
        else:
            icon = "📄" if self.mode == "pdf2img" else "🖼"
            self.pcanvas.create_text(cx2, y0+(lby-y0)//2, text=icon,
                font=("Segoe UI Emoji",22), fill=TEXT_DIM, tags=(tag,"card"))
        self.pcanvas.create_line(x0+10, lby, x0+self.ICW-10, lby,
                                 fill=BORDER, tags=(tag,"card"))
        fname = label if len(label)<=14 else label[:12]+"…"
        self.pcanvas.create_text(cx2, lby+14, text=fname, font=FONT_XS,
                                 fill=TEXT_DIM, width=self.ICW-10,
                                 justify="center", tags=(tag,"card"))
        self.pcanvas.create_text(cx2, lby+30, text=f"{idx+1}",
                                 font=(FM,9,"bold"), fill=ACCENT, tags=(tag,"card"))

    def _draw_hover(self, idx):
        if self.mode != "img2pdf": return
        if idx >= len(self.img_files): return
        x0, y0 = self._img_card_xy(idx)
        rr(self.pcanvas, x0-3, y0-3, x0+self.ICW+3, y0+self.ICH+3,
           r=15, fill="", outline=ACCENT, width=3, tags="ihov")
        bx, by, r2 = x0+self.ICW-14, y0+14, 11
        self.pcanvas.create_oval(bx-r2,by-r2,bx+r2,by+r2,
            fill=DANGER, outline="white", width=2, tags=("ihov","idel"))
        self.pcanvas.create_text(bx, by, text="✕",
            font=(FM,9,"bold"), fill="white", tags=("ihov","idel"))

    def _img_clear_hover(self, _=None):
        self.pcanvas.delete("ihov"); self.img_hover = None
        if self.img_drag_src is None:
            self.pcanvas.config(cursor="")

    def _img_on_hover(self, event):
        if self.mode != "img2pdf" or self.img_drag_src is not None: return
        cx = self.pcanvas.canvasx(event.x)
        cy = self.pcanvas.canvasy(event.y)
        idx = self._xy_to_card(cx, cy)
        if idx != self.img_hover:
            self.pcanvas.delete("ihov")
            self.img_hover = idx
            if idx is not None: self._draw_hover(idx)
            self.pcanvas.config(cursor="fleur" if idx is not None else "")

    def _img_on_press(self, event):
        if self.mode != "img2pdf": return
        cx = self.pcanvas.canvasx(event.x)
        cy = self.pcanvas.canvasy(event.y)
        for item in self.pcanvas.find_overlapping(cx-4,cy-4,cx+4,cy+4):
            if "idel" in self.pcanvas.gettags(item):
                if self.img_hover is not None:
                    self._img_delete(self.img_hover)
                return
        idx = self._xy_to_card(cx, cy)
        if idx is not None:
            self.img_drag_src   = idx
            self.img_drag_tgt   = None
            self.img_drag_moved = False

    def _img_on_b1motion(self, event):
        if self.img_drag_src is None: return
        self.pcanvas.delete("ihov"); self.img_hover = None
        if not self.img_drag_moved:
            self.pcanvas.config(cursor="fleur")
        self.img_drag_moved = True
        cx = self.pcanvas.canvasx(event.x)
        cy = self.pcanvas.canvasy(event.y)
        tgt = self._xy_to_insert(cx, cy)
        if tgt != self.img_drag_tgt:
            self.img_drag_tgt = tgt; self._render_preview(insert_at=tgt)
        self._img_draw_ghost(cx, cy)
        h = self.pcanvas.winfo_height()
        if event.y < 40:     self.pcanvas.yview_scroll(-1,"units")
        elif event.y > h-40: self.pcanvas.yview_scroll( 1,"units")

    def _img_draw_ghost(self, cx, cy):
        """드래그 중인 이미지를 마우스 위치에 작게 띄워 '들고 있는' 느낌을 준다."""
        self.pcanvas.delete("ighost")
        self.img_ghost_photos.clear()
        if self.img_drag_src is None or self.img_drag_src >= len(self.img_thumbs): return
        thumb = self.img_thumbs[self.img_drag_src]
        gw, gh = int(self.ICW*0.72), int(self.ICH*0.72)
        x0, y0 = cx-gw//2, cy-gh//2
        for d, col in [(5,SH1),(3,SH2)]:
            rr(self.pcanvas, x0+d, y0+d, x0+gw+d, y0+gh+d,
               r=10, fill=col, outline="", tags="ighost")
        rr(self.pcanvas, x0, y0, x0+gw, y0+gh,
           r=10, fill=CARD, outline=ACCENT, width=2, tags="ighost")
        if thumb:
            pad = 6
            sc  = min((gw-pad*2)/thumb.width, (gh-pad*2)/thumb.height)
            nw, nh = max(1,int(thumb.width*sc)), max(1,int(thumb.height*sc))
            img = thumb.resize((nw, nh), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.img_ghost_photos.append(photo)
            self.pcanvas.create_image(cx, cy, image=photo, tags="ighost")
        else:
            icon = "📄" if self.mode == "pdf2img" else "🖼"
            self.pcanvas.create_text(cx, cy, text=icon,
                font=("Segoe UI Emoji",18), fill=TEXT_DIM, tags="ighost")

    def _img_on_release(self, event):
        if self.img_drag_src is None: return
        if self.img_drag_moved and self.img_drag_tgt is not None:
            src, tgt = self.img_drag_src, self.img_drag_tgt
            if tgt > src: tgt -= 1
            if src != tgt:
                f = self.img_files.pop(src)
                t = self.img_thumbs.pop(src)
                self.img_files.insert(tgt, f)
                self.img_thumbs.insert(tgt, t)
        self.img_drag_src = self.img_drag_tgt = None
        self.img_drag_moved = False
        self.pcanvas.config(cursor="")
        self._render_preview()

    def _xy_to_card(self, cx, cy):
        cols = self._img_cols()
        col  = int((cx-self.IPAD)//(self.ICW+self.IPAD))
        row  = int((cy-self.IPAD)//(self.ICH+self.IPAD))
        if not (0 <= col < cols): return None
        idx  = row*cols+col
        if not (0 <= idx < len(self.img_files)): return None
        x0, y0 = self._img_card_xy(idx)
        return idx if (x0<=cx<=x0+self.ICW and y0<=cy<=y0+self.ICH) else None

    def _xy_to_insert(self, cx, cy):
        cols = self._img_cols()
        col  = int((cx-self.IPAD/2)//(self.ICW+self.IPAD))
        row  = int((cy-self.IPAD/2)//(self.ICH+self.IPAD))
        col  = max(0, min(col, cols-1))
        idx  = row*cols+col
        x0, _ = self._img_card_xy(idx) if idx < len(self.img_files) else (0,0)
        if cx > x0+self.ICW/2: idx += 1
        return max(0, min(idx, len(self.img_files)))

    def _img_delete(self, idx):
        if 0 <= idx < len(self.img_files):
            self.img_files.pop(idx)
            self.img_thumbs.pop(idx)
            self.img_hover = None
            if not self.img_files:
                self._reset()
            else:
                self._set_status(f"🖼  이미지  ·  {len(self.img_files)}개  →  PDF로 변환")
                self._render_preview()

    # ── 저장 ────────────────────────────────────────────────
    def _do_save(self):
        if   self.mode == "pdf2img": self._save_pdf2img()
        elif self.mode == "img2pdf": self._save_img2pdf()

    def _save_pdf2img(self):
        if not PREVIEW_OK:
            messagebox.showerror("오류","pip install pymupdf Pillow 필요"); return
        out_dir = filedialog.askdirectory(title="저장 폴더 선택",
            initialdir=os.path.dirname(self.pdf_path_str) if self.pdf_path_str else "")
        if not out_dir: return
        base = self.out_name.get().strip() or os.path.splitext(os.path.basename(self.pdf_path_str))[0]
        sc   = 300 / 72   # DPI 300 고정 (최고 화질)
        try:
            doc = fitz.open(self.pdf_path_str); n = len(doc)
            for i, page in enumerate(doc):
                pix = page.get_pixmap(matrix=fitz.Matrix(sc, sc), alpha=False)
                img = Image.frombytes("RGB",[pix.width,pix.height],pix.samples)
                out = os.path.join(out_dir, f"{base}_p{i+1:03d}.png")
                img.save(out)
                self.update()
            doc.close()
            messagebox.showinfo("완료", f"{n}개 PNG 이미지 저장!\n{out_dir}")
        except Exception as e:
            messagebox.showerror("오류", str(e))

    def _save_img2pdf(self):
        base = self.out_name.get().strip() or os.path.splitext(os.path.basename(self.img_files[0]))[0]
        init_dir = os.path.dirname(self.img_files[0]) if self.img_files else ""
        out  = filedialog.asksaveasfilename(
            title="PDF로 저장", defaultextension=".pdf",
            filetypes=[("PDF","*.pdf")], initialdir=init_dir, initialfile=f"{base}.pdf")
        if not out: return
        try:
            doc = fitz.open()
            for p in self.img_files:
                img_doc  = fitz.open(p)                   # 이미지 열기
                pdfbytes = img_doc.convert_to_pdf()        # PDF 바이트로 변환
                img_pdf  = fitz.open("pdf", pdfbytes)      # PDF 문서로 열기
                doc.insert_pdf(img_pdf)                    # 합치기
                img_doc.close(); img_pdf.close()
            doc.save(out)
            doc.close()
            messagebox.showinfo("완료", f"PDF 저장 완료!\n{out}")
        except Exception as e:
            messagebox.showerror("오류", str(e))


# ══════════════════════════════════════════════════════════
#  메인 앱
# ══════════════════════════════════════════════════════════
class App(TkinterDnD.Tk if DND_OK else tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF 편집기")
        sw,sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w,h   = min(1040,sw-60), min(780,sh-60)
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.minsize(780,580); self.configure(bg=BG)
        try:
            self.iconbitmap(default=_resource_path("icon.ico"))
        except Exception:
            pass
        self._build()
        self.after(3000, lambda: _check_update(self))  # 3초 후 백그라운드 업데이트 확인
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)

    def _on_close_request(self):
        """내보내기 하지 않은 변경사항이 있는 상태로 프로그램을 통째로
        종료하려 하면 한 번 확인한다. 탭을 바꾸는 것과는 무관 — 창을 닫을
        때만(X 버튼/Alt+F4 등) 호출된다."""
        ot = self.tabs.get("organize")
        if ot is not None and ot.has_unsaved_changes():
            if not messagebox.askyesno(
                "종료 확인",
                "내보내기 하지 않은 변경사항이 있습니다.\n그래도 종료하시겠습니까?",
                parent=self):
                return
        self.destroy()

    def _build(self):
        # 헤더
        hdr = tk.Frame(self, bg=PANEL)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  PDF 편집기", font=(FM,13,"bold"),
                 bg=PANEL, fg=TEXT).pack(side="left", pady=12)
        tk.Label(hdr, text=f"v{VERSION}", font=FONT_S,
                 bg=PANEL, fg=TEXT_DIM).pack(side="left", padx=(2,8), pady=12)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # 탭 버튼 (선택 탭: Bold + 메인 컬러 배경 / 비선택: 연한 배경)
        tb = tk.Frame(self, bg=BG)
        tb.pack(fill="x", padx=16, pady=10)
        self.tabs = {}; self.tbtns = {}
        self._active_tab = None

        for key,lbl in [("organize","정리  (병합 · 분할)"),("convert","변환  (PDF ↔ 이미지)")]:
            b = tk.Button(tb, text=lbl, font=FONT_SB, bg=TOOLBAR, fg=TEXT_DIM,
                          relief="flat", padx=20, pady=10, bd=0, cursor="hand2",
                          command=lambda k=key: self._sw(k))
            b.bind("<Enter>", lambda e, k=key: self._tab_hover(k, True))
            b.bind("<Leave>", lambda e, k=key: self._tab_hover(k, False))
            b.pack(side="left", padx=(0,4)); self.tbtns[key] = b

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # 상태 표시줄 (창 맨 아래 고정 — cont 보다 먼저 패킹해 공간 확보)
        self.status_var = tk.StringVar(value="")
        status_bar = tk.Frame(self, bg=PANEL)
        tk.Frame(status_bar, bg=BORDER, height=1).pack(fill="x")
        tk.Label(status_bar, textvariable=self.status_var, font=FONT_S,
                 bg=PANEL, fg=TEXT_DIM, anchor="w").pack(fill="x", padx=14, pady=6)
        status_bar.pack(fill="x", side="bottom")

        cont = tk.Frame(self, bg=BG); cont.pack(fill="both", expand=True)
        self.tabs["organize"] = OrganizeTab(cont)
        self.tabs["convert"]  = ConvertTab(cont)
        self.tabs["organize"].status_cb = self._update_status_organize
        self.tabs["convert"].status_cb  = self._update_status_convert
        self._sw("organize")

    def _tab_hover(self, key, entering):
        b = self.tbtns[key]
        base = ACCENT if self._active_tab == key else TOOLBAR
        b.config(bg=_shade(base, 0.9) if entering else base)

    def _sw(self, key):
        self._active_tab = key
        for f in self.tabs.values(): f.pack_forget()
        self.tabs[key].pack(fill="both", expand=True)
        for k,b in self.tbtns.items():
            active = (k == key)
            b.config(bg=ACCENT if active else TOOLBAR,
                     fg="white" if active else TEXT_DIM,
                     font=FONT_B if active else FONT_SB)
        if key == "organize":
            ot = self.tabs["organize"]
            self._update_status_organize(len({pg["src"] for pg in ot.pages}),
                                          len(ot.checked), len(ot.pages))
        else:
            self._update_status_convert(self.tabs["convert"].status_lbl.cget("text"))

    # ── 상태 표시줄 갱신 (기존에 이미 추적 중인 정보만 표시) ──
    def _update_status_organize(self, files, checked, pages):
        if pages == 0:
            self.status_var.set("파일을 추가하면 상태가 표시됩니다")
        else:
            self.status_var.set(f"파일 {files}개  |  선택 {checked}개  |  총 {pages}페이지")

    def _update_status_convert(self, text):
        self.status_var.set(text if text else "파일을 추가하면 상태가 표시됩니다")


if __name__ == "__main__":
    App().mainloop()
