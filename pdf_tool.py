"""
PDF 도구  ·  무료 · 오프라인 · 완전 로컬
  ▸ 정리 탭  : 드래그 정렬 · 체크박스 · 호버 툴바 · 미리보기 + 편집
  ▸ 변환 탭  : PDF → 이미지 / 이미지 → PDF
"""
import sys, os, shutil, subprocess, threading, zipfile

VERSION = "20260826.1446"                       # 배포.bat 이 자동 업데이트
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
    from PIL import Image, ImageTk
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
PREV_BG  = "#140830"   # 미리보기 배경 (별도 다크 테마 유지)

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
DEFAULT_ANNOT_SIZE  = 14.0     # pt
DEFAULT_ANNOT_COLOR = ACCENT


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
#  텍스트 속성 패널 (PreviewWin 우측에 붙는다, 선택 시에만 표시)
# ══════════════════════════════════════════════════════════
class TextPropPanel(tk.Frame):
    ALIGN_CHOICES = [("좌측", "left"), ("가운데", "center"), ("우측", "right")]

    def __init__(self, master, owner):
        super().__init__(master, bg="#1e0c44", width=230)
        self.owner = owner          # PreviewWin 인스턴스 (변경 통지용)
        self.annot = None
        self.pack_propagate(False)  # 내용과 무관하게 폭 고정
        self._build()

    def _build(self):
        pad = dict(padx=14)
        tk.Label(self, text="텍스트 속성", font=FONT_B, bg="#1e0c44", fg="#e0d0ff")\
            .pack(anchor="w", padx=14, pady=(12,4))
        tk.Frame(self, bg="#3a2a5a", height=1).pack(fill="x", padx=14, pady=(0,8))

        # ── 내용 ──────────────────────────────────────────
        tk.Label(self, text="내용", font=FONT_S, bg="#1e0c44", fg="#c8a8ff").pack(anchor="w", **pad)
        self.text_var = tk.StringVar()
        e_text = tk.Entry(self, textvariable=self.text_var, font=FONT, bg="white", fg="#222")
        e_text.pack(fill="x", padx=14, pady=(2,8))
        e_text.bind("<Return>", lambda e: self._apply_text())
        e_text.bind("<FocusOut>", lambda e: self._apply_text())

        # ── 위치 (X/Y, mm) ───────────────────────────────
        tk.Label(self, text="위치 (기준: 페이지 좌측 상단)", font=FONT_S,
                 bg="#1e0c44", fg="#c8a8ff").pack(anchor="w", padx=14, pady=(4,2))

        xrow = tk.Frame(self, bg="#1e0c44"); xrow.pack(fill="x", padx=14)
        tk.Label(xrow, text="X", font=FONT_S, bg="#1e0c44", fg="#e0d0ff", width=2).pack(side="left")
        self.x_var = tk.StringVar()
        e_x = tk.Entry(xrow, textvariable=self.x_var, font=FONT, width=9, bg="white", fg="#222")
        e_x.pack(side="left")
        tk.Label(xrow, text="mm", font=FONT_XS, bg="#1e0c44", fg="#9a8ab8").pack(side="left", padx=(4,0))
        e_x.bind("<Return>", lambda e: self._apply_xy())
        e_x.bind("<FocusOut>", lambda e: self._apply_xy())

        yrow = tk.Frame(self, bg="#1e0c44"); yrow.pack(fill="x", padx=14, pady=(4,4))
        tk.Label(yrow, text="Y", font=FONT_S, bg="#1e0c44", fg="#e0d0ff", width=2).pack(side="left")
        self.y_var = tk.StringVar()
        e_y = tk.Entry(yrow, textvariable=self.y_var, font=FONT, width=9, bg="white", fg="#222")
        e_y.pack(side="left")
        tk.Label(yrow, text="mm", font=FONT_XS, bg="#1e0c44", fg="#9a8ab8").pack(side="left", padx=(4,0))
        e_y.bind("<Return>", lambda e: self._apply_xy())
        e_y.bind("<FocusOut>", lambda e: self._apply_xy())

        self.page_size_lbl = tk.Label(self, text="", font=FONT_XS, bg="#1e0c44", fg="#7a6a98")
        self.page_size_lbl.pack(anchor="w", padx=14, pady=(2,8))

        # ── 글꼴 ──────────────────────────────────────────
        tk.Label(self, text="글꼴", font=FONT_S, bg="#1e0c44", fg="#c8a8ff").pack(anchor="w", **pad)
        self.font_var = tk.StringVar()
        self.font_combo = ttk.Combobox(self, textvariable=self.font_var, values=self._font_list(),
                                        state="readonly", font=FONT_S)
        self.font_combo.pack(fill="x", padx=14, pady=(2,8))
        self.font_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_font())

        # ── 크기 ──────────────────────────────────────────
        tk.Label(self, text="크기 (pt)", font=FONT_S, bg="#1e0c44", fg="#c8a8ff").pack(anchor="w", **pad)
        self.size_var = tk.StringVar()
        e_size = tk.Entry(self, textvariable=self.size_var, font=FONT, width=9, bg="white", fg="#222")
        e_size.pack(anchor="w", padx=14, pady=(2,8))
        e_size.bind("<Return>", lambda e: self._apply_size())
        e_size.bind("<FocusOut>", lambda e: self._apply_size())

        # ── 색상 ──────────────────────────────────────────
        crow = tk.Frame(self, bg="#1e0c44"); crow.pack(fill="x", padx=14, pady=(0,8))
        tk.Label(crow, text="색상", font=FONT_S, bg="#1e0c44", fg="#c8a8ff").pack(side="left")
        self.color_btn = tk.Button(crow, text="   ", bg=DEFAULT_ANNOT_COLOR, width=4,
                                    relief="flat", bd=1, cursor="hand2", command=self._pick_color)
        self.color_btn.pack(side="left", padx=8)

        # ── 굵게 / 기울임 ─────────────────────────────────
        birow = tk.Frame(self, bg="#1e0c44"); birow.pack(fill="x", padx=10, pady=(0,8))
        self.bold_var = tk.BooleanVar()
        self.italic_var = tk.BooleanVar()
        tk.Checkbutton(birow, text="굵게", variable=self.bold_var, command=self._apply_style,
                       bg="#1e0c44", fg="#e0d0ff", selectcolor="#2e1a55",
                       activebackground="#1e0c44", font=FONT_S, bd=0,
                       highlightthickness=0).pack(side="left", padx=4)
        tk.Checkbutton(birow, text="기울임", variable=self.italic_var, command=self._apply_style,
                       bg="#1e0c44", fg="#e0d0ff", selectcolor="#2e1a55",
                       activebackground="#1e0c44", font=FONT_S, bd=0,
                       highlightthickness=0).pack(side="left", padx=4)

        # ── 정렬 ──────────────────────────────────────────
        tk.Label(self, text="정렬", font=FONT_S, bg="#1e0c44", fg="#c8a8ff").pack(anchor="w", **pad)
        self.align_var = tk.StringVar()
        self.align_combo = ttk.Combobox(
            self, textvariable=self.align_var,
            values=[label for label, _ in self.ALIGN_CHOICES],
            state="readonly", font=FONT_S)
        self.align_combo.pack(fill="x", padx=14, pady=(2,8))
        self.align_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_align())

        # ── 회전 (텍스트 자체 회전 — 페이지 회전과 별개) ──
        tk.Label(self, text="회전 (°)", font=FONT_S, bg="#1e0c44", fg="#c8a8ff").pack(anchor="w", **pad)
        self.rot_var = tk.StringVar()
        e_rot = tk.Entry(self, textvariable=self.rot_var, font=FONT, width=9, bg="white", fg="#222")
        e_rot.pack(anchor="w", padx=14, pady=(2,8))
        e_rot.bind("<Return>", lambda e: self._apply_rotation())
        e_rot.bind("<FocusOut>", lambda e: self._apply_rotation())

    def _font_list(self):
        try:
            from tkinter import font as tkfont
            names = sorted(set(tkfont.families(self)))
            return names if names else [DEFAULT_ANNOT_FONT]
        except Exception:
            return [DEFAULT_ANNOT_FONT]

    # ── annot 표시 ────────────────────────────────────────
    def show_annot(self, annot, page_w_pt, page_h_pt):
        self.annot = annot
        if annot is None:
            return
        self.text_var.set(annot.get("text", ""))
        self.x_var.set(f"{pt_to_mm(annot['x']):.2f}")
        self.y_var.set(f"{pt_to_mm(annot['y']):.2f}")
        font_name = annot.get("font", DEFAULT_ANNOT_FONT)
        self.font_var.set(font_name if font_name in self.font_combo["values"] else DEFAULT_ANNOT_FONT)
        self.size_var.set(f"{annot.get('font_size', DEFAULT_ANNOT_SIZE):.2f}")
        self.bold_var.set(bool(annot.get("bold", False)))
        self.italic_var.set(bool(annot.get("italic", False)))
        align_key = annot.get("align", "left")
        label = next((lbl for lbl, val in self.ALIGN_CHOICES if val == align_key), "좌측")
        self.align_var.set(label)
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
        self.y_var.set(f"{pt_to_mm(self.annot['y']):.2f}")

    # ── 각 필드 적용 (Enter / 포커스 아웃 시점에 반영) ───────
    def _apply_text(self):
        if self.annot is None: return
        self.annot["text"] = self.text_var.get()
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
        # 내부 저장은 항상 pt, 정밀도를 그대로 유지한다 (화면 표시만 반올림)
        self.annot["x"] = mm_to_pt(x_mm)
        self.annot["y"] = mm_to_pt(y_mm)
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
        self.annot["rotation"] = rot
        self.rot_var.set(f"{rot:.1f}")
        self.owner._on_annot_prop_changed()

    def _apply_font(self):
        if self.annot is None: return
        self.annot["font"] = self.font_var.get() or DEFAULT_ANNOT_FONT
        self.owner._on_annot_prop_changed()

    def _apply_style(self):
        if self.annot is None: return
        self.annot["bold"] = bool(self.bold_var.get())
        self.annot["italic"] = bool(self.italic_var.get())
        self.owner._on_annot_prop_changed()

    def _apply_align(self):
        if self.annot is None: return
        label = self.align_var.get()
        val = next((v for l, v in self.ALIGN_CHOICES if l == label), "left")
        self.annot["align"] = val
        self.owner._on_annot_prop_changed()

    def _pick_color(self):
        if self.annot is None: return
        from tkinter import colorchooser
        cur = self.annot.get("color", DEFAULT_ANNOT_COLOR)
        _, hexcol = colorchooser.askcolor(color=cur, parent=self, title="텍스트 색상 선택")
        if hexcol:
            self.annot["color"] = hexcol
            self.color_btn.config(bg=hexcol)
            self.owner._on_annot_prop_changed()


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
        # 마지막 _show() 렌더링 기준 좌표 변환 파라미터 (screen<->pdf 변환용)
        self._sc      = None
        self._cx       = None
        self._cy       = None
        self._cur_pw   = None
        self._cur_ph   = None
        self._cur_rot  = 0

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h   = min(940, sw-60), min(820, sh-60)
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.title("미리보기")
        self.configure(bg=PREV_BG)
        self.transient(parent)
        self.grab_set()
        self.focus_set()
        self.resizable(True, True)

        self._build()
        self.after(60, self._show)

        # 속성 패널의 입력창(Entry/Combobox)에 포커스가 있을 때는 아래
        # 단축키들이 가로채면 안 된다 (예: X 좌표에 "-999" 를 입력하려는데
        # "-" 가 축소 단축키로 먼저 소비되는 문제 방지).
        self.bind("<Left>",       lambda e: None if self._focus_in_entry() else self._go(-1))
        self.bind("<Right>",      lambda e: None if self._focus_in_entry() else self._go(1))
        self.bind("<Escape>",     lambda e: self.destroy())
        self.bind("<plus>",       lambda e: None if self._focus_in_entry() else self._zoom(1.25))
        self.bind("<equal>",      lambda e: None if self._focus_in_entry() else self._zoom(1.25))
        self.bind("<minus>",      lambda e: None if self._focus_in_entry() else self._zoom(1/1.25))
        self.bind("<0>",          lambda e: None if self._focus_in_entry() else self._zoom_reset())
        self.bind("<Delete>",     lambda e: None if self._focus_in_entry() else self._delete_selected_annot())

    def _build(self):
        # ── 상단 타이틀 바 ───────────────────────────────
        top = tk.Frame(self, bg=PREV_BG)
        top.pack(fill="x", padx=20, pady=(14, 0))
        self.title_lbl = tk.Label(top, text="", font=FONT_B,
                                  bg=PREV_BG, fg="#c8b0f0")
        self.title_lbl.pack(side="left")
        tk.Button(top, text="✕", command=self.destroy,
                  bg=PREV_BG, fg="#665588", font=(FM, 14),
                  relief="flat", bd=0, cursor="hand2",
                  activebackground=PREV_BG).pack(side="right")
        self.edit_btn = tk.Button(top, text="✎ 편집 모드", command=self._toggle_edit,
                  bg="#2e1a55", fg="#c8a8ff", font=FONT_B,
                  relief="flat", padx=12, pady=5, cursor="hand2",
                  bd=0, activebackground="#3e2a70")
        self.edit_btn.pack(side="right", padx=(0,10))

        # ── 편집 툴바 (편집 모드일 때만 표시) ────────────
        self.edit_toolbar = tk.Frame(self, bg="#1e0c44")
        self.tool_btns = {}
        for key, label in [("select","🖱 선택"), ("text","T 텍스트")]:
            b = tk.Button(self.edit_toolbar, text=label,
                          command=lambda k=key: self._set_tool(k),
                          bg="#2e1a55", fg="#c8a8ff", font=FONT_B,
                          relief="flat", padx=14, pady=6, cursor="hand2",
                          bd=0, activebackground="#3e2a70")
            b.pack(side="left", padx=(20 if key=="select" else 4, 4), pady=6)
            self.tool_btns[key] = b

        # ── 이미지 캔버스 + 우측 속성 패널 ──────────────────
        mid = tk.Frame(self, bg=PREV_BG)
        self.preview_cf = mid
        mid.pack(fill="both", expand=True)
        # 속성 패널은 텍스트를 선택했을 때만 pack() 되어 나타난다 (17번 요구사항)
        self.prop_panel = TextPropPanel(mid, owner=self)

        cf = tk.Frame(mid, bg=PREV_BG)
        cf.pack(side="left", fill="both", expand=True, padx=30, pady=12)
        self.canvas = tk.Canvas(cf, bg=PREV_BG, bd=0, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>",      self._on_resize)
        self.canvas.bind("<MouseWheel>",
                         lambda e: self._zoom(1.15 if e.delta > 0 else 1/1.15))
        self.canvas.bind("<ButtonPress-1>",  self._on_canvas_press)
        self.canvas.bind("<B1-Motion>",      self._on_canvas_motion)
        self.canvas.bind("<ButtonRelease-1>",self._on_canvas_release)

        # ── 하단 컨트롤 바 (네비 + 편집) ────────────────
        nav = tk.Frame(self, bg="#1e0c44", pady=10)
        nav.pack(fill="x")

        # 이전 / 다음
        self.btn_prev = tk.Button(nav, text="◀", command=lambda: self._go(-1),
                                  bg="#2e1a55", fg="#c8a8ff", font=FONT_B,
                                  relief="flat", padx=14, pady=8, cursor="hand2",
                                  bd=0, activebackground="#3e2a70")
        self.btn_prev.pack(side="left", padx=(20, 4))

        self.page_lbl = tk.Label(nav, text="", font=FONT_B,
                                 bg="#1e0c44", fg="#e0d0ff")
        self.page_lbl.pack(side="left", padx=8)

        self.btn_next = tk.Button(nav, text="▶", command=lambda: self._go(1),
                                  bg="#2e1a55", fg="#c8a8ff", font=FONT_B,
                                  relief="flat", padx=14, pady=8, cursor="hand2",
                                  bd=0, activebackground="#3e2a70")
        self.btn_next.pack(side="left", padx=(4, 20))

        # ── 편집 버튼들 (가운데) ─────────────────────────
        edit = tk.Frame(nav, bg="#1e0c44")
        edit.pack(side="left", expand=True)

        for txt, cmd, bg in [
            ("↺ 왼쪽 90°", lambda: self._rotate(-90), "#2e1a55"),
            ("↻ 오른쪽 90°", lambda: self._rotate(90),  "#2e1a55"),
            ("🗑 이 페이지 삭제", self._delete,         DANGER),
        ]:
            b = tk.Button(edit, text=txt, command=cmd, bg=bg,
                          fg="white", font=FONT, relief="flat",
                          padx=12, pady=7, cursor="hand2", bd=0)
            b.pack(side="left", padx=5)

        # ── 줌 버튼들 ────────────────────────────────────
        zoom_fr = tk.Frame(nav, bg="#1e0c44")
        zoom_fr.pack(side="right", padx=(0, 12))

        tk.Button(zoom_fr, text="−", command=lambda: self._zoom(1/1.25),
                  bg="#2e1a55", fg="#c8a8ff", font=(FM, 13, "bold"),
                  relief="flat", padx=10, pady=6, cursor="hand2",
                  bd=0, activebackground="#3e2a70").pack(side="left", padx=2)

        self.zoom_lbl = tk.Label(zoom_fr, text="100%", width=5,
                                 font=FONT, bg="#1e0c44", fg="#e0d0ff")
        self.zoom_lbl.pack(side="left")

        tk.Button(zoom_fr, text="+", command=lambda: self._zoom(1.25),
                  bg="#2e1a55", fg="#c8a8ff", font=(FM, 13, "bold"),
                  relief="flat", padx=10, pady=6, cursor="hand2",
                  bd=0, activebackground="#3e2a70").pack(side="left", padx=2)

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
            for d, col in [(8,"#0a0520"),(5,"#140830"),(2,"#1e0c44")]:
                self.canvas.create_rectangle(
                    ix-iw//2+d, iy-ih//2+d, ix+iw//2+d, iy+ih//2+d,
                    fill=col, outline="")
            # 흰 테두리 + 이미지
            self.canvas.create_rectangle(
                ix-iw//2-3, iy-ih//2-3, ix+iw//2+3, iy+ih//2+3,
                fill="white", outline="#443366", width=1)
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
        if self.edit_mode and self.tool == "select":
            hit = self._hit_test(e.x, e.y)
            if hit is not None:
                self._select_annot(hit["id"])
                if self._sc is not None:
                    px_pdf, py_pdf = screen_to_pdf(
                        e.x, e.y, self._cur_pw, self._cur_ph,
                        self._cur_rot, self._sc, self._cx, self._cy)
                    self._move_state = {
                        "annot_id": hit["id"],
                        "off_x": hit["x"] - px_pdf,
                        "off_y": hit["y"] - py_pdf,
                    }
                return
            else:
                self._select_annot(None)
        self._pan_start(e)

    def _on_canvas_motion(self, e):
        if self._move_state is not None:
            self._drag_annot(e)
            return
        self._pan_move(e)

    def _on_canvas_release(self, e):
        if self._move_state is not None:
            self._move_state = None
            return
        self._pan_end(e)

    # ── 팬(이동) ─────────────────────────────────────────────
    def _pan_start(self, e):
        self._drag_sx = e.x
        self._drag_sy = e.y
        self.canvas.config(cursor="fleur")   # 십자 이동 커서

    def _pan_move(self, e):
        if self._drag_sx is None: return
        self.pan_x += e.x - self._drag_sx
        self.pan_y += e.y - self._drag_sy
        self._drag_sx = e.x
        self._drag_sy = e.y
        self._show()

    def _pan_end(self, e):
        self._drag_sx = None
        self._drag_sy = None
        self.canvas.config(cursor="")

    # ── 편집 모드 / 도구 선택 ─────────────────────────────────
    def _toggle_edit(self):
        self.edit_mode = not self.edit_mode
        self.edit_btn.config(bg=ACCENT if self.edit_mode else "#2e1a55",
                              fg="white" if self.edit_mode else "#c8a8ff")
        if self.edit_mode:
            self.edit_toolbar.pack(fill="x", before=self.preview_cf)
            self._set_tool(self.tool)
        else:
            self.edit_toolbar.pack_forget()
            self._select_annot(None)
        self._show()

    def _set_tool(self, key):
        self.tool = key
        for k, b in self.tool_btns.items():
            active = (k == key)
            b.config(bg=ACCENT if active else "#2e1a55",
                     fg="white" if active else "#c8a8ff")
        self.canvas.config(cursor="xterm" if key == "text" else "")

    def _focus_in_entry(self):
        """속성 패널의 입력창에 포커스가 있는지 확인 (단축키 충돌 방지용)."""
        w = self.focus_get()
        return isinstance(w, (tk.Entry, tk.Spinbox, tk.Text, ttk.Entry, ttk.Combobox))

    # ── annot(텍스트) 선택/생성/이동/삭제 ─────────────────────
    def _hit_test(self, ex, ey):
        """캔버스 좌표(ex,ey) 위에 있는 현재 페이지의 annot 을 찾는다."""
        pg = self.pages[self.idx]
        annots = {a["id"]: a for a in pg.get("annots", [])}
        for item in reversed(self.canvas.find_overlapping(ex-2, ey-2, ex+2, ey+2)):
            for t in self.canvas.gettags(item):
                if t.startswith("annot_"):
                    aid = int(t.split("_")[1])
                    if aid in annots:
                        return annots[aid]
        return None

    def _cur_page(self):
        return self.pages[self.idx]

    def _find_annot(self, aid):
        for a in self._cur_page().get("annots", []):
            if a["id"] == aid:
                return a
        return None

    def _select_annot(self, aid):
        self.selected_id = aid
        annot = self._find_annot(aid) if aid is not None else None
        if annot is None:
            self.prop_panel.pack_forget()
        else:
            pg = self._cur_page()
            self.prop_panel.show_annot(annot, pg.get("page_w_pt"), pg.get("page_h_pt"))
            self.prop_panel.pack(side="right", fill="y")
        self._show()

    def _on_annot_prop_changed(self):
        """속성 패널에서 값이 바뀌었을 때 캔버스에 즉시 반영."""
        self._show()
        if self.on_change: self.on_change()

    def _ask_text(self):
        """텍스트 입력 대화상자. 테스트에서는 이 메서드를 mock 처리한다."""
        from tkinter import simpledialog
        return simpledialog.askstring("텍스트 입력", "내용을 입력하세요:", parent=self)

    def _create_text_at(self, ex, ey):
        if self._sc is None: return
        text = self._ask_text()
        if not text: return
        x_pt, y_pt = screen_to_pdf(ex, ey, self._cur_pw, self._cur_ph,
                                    self._cur_rot, self._sc, self._cx, self._cy)
        pg = self.pages[self.idx]
        annot = {
            "id": next(_id_gen), "type": "text", "text": text,
            "x": x_pt, "y": y_pt,
            "font": DEFAULT_ANNOT_FONT, "font_size": DEFAULT_ANNOT_SIZE,
            "color": DEFAULT_ANNOT_COLOR, "bold": False, "italic": False,
            "align": "left", "rotation": 0.0,
        }
        pg.setdefault("annots", []).append(annot)
        self._select_annot(annot["id"])
        if self.on_change: self.on_change()

    def _drag_annot(self, e):
        if self._sc is None or self._move_state is None: return
        a = self._find_annot(self._move_state["annot_id"])
        if a is None: return
        px_pdf, py_pdf = screen_to_pdf(e.x, e.y, self._cur_pw, self._cur_ph,
                                        self._cur_rot, self._sc, self._cx, self._cy)
        a["x"] = px_pdf + self._move_state["off_x"]
        a["y"] = py_pdf + self._move_state["off_y"]
        self.prop_panel.refresh_xy_only()
        self._show()

    def _delete_selected_annot(self, e=None):
        if self.selected_id is None: return
        pg = self.pages[self.idx]
        pg["annots"] = [a for a in pg.get("annots", []) if a["id"] != self.selected_id]
        self.selected_id = None
        self.prop_panel.pack_forget()
        self._show()
        if self.on_change: self.on_change()

    def _draw_annots(self, pg):
        for a in pg.get("annots", []):
            if a.get("type") != "text": continue
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
            try:
                item = self.canvas.create_text(
                    px, py, text=a.get("text", ""), anchor="nw",
                    font=font_spec, fill=a.get("color", DEFAULT_ANNOT_COLOR),
                    justify=a.get("align", "left"), angle=angle,
                    tags=(f"annot_{a['id']}", "annot"))
            except Exception:
                continue
            if self.edit_mode and a["id"] == self.selected_id:
                bbox = self.canvas.bbox(item)
                if bbox:
                    pad = 4
                    self.canvas.create_rectangle(
                        bbox[0]-pad, bbox[1]-pad, bbox[2]+pad, bbox[3]+pad,
                        outline=ACCENT, width=2, dash=(4,2),
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
        self._build()

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
        mkbtn(tb, "▶  PDF 내보내기", self._export, bg=ACCENT,
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
                text="PDF 파일을 여기에 드래그하세요",
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
            # 카드 위에서는 "이동 가능" 커서로 드래그 가능함을 표시
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
        # 단순 클릭은 아무 동작 없음 (미리보기는 🔍 버튼으로만)
        self.drag_src = self.drag_tgt = None
        self.drag_moved = False
        self.canvas.config(cursor="")
        self._render()

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
            self._render()
        elif key == "dup":
            pg = dict(self.pages[idx]); pg["id"] = next(_id_gen)
            # annots 는 리스트(가변 객체)이므로 얕은 복사(dict())만 하면
            # 원본과 복제본이 같은 리스트를 공유하게 된다 — 반드시 새 리스트로
            # 깊은 복사해서 이후 편집이 서로 독립적이도록 한다.
            pg["annots"] = [dict(a) for a in pg.get("annots", [])]
            self.pages.insert(idx+1, pg); self._render()
        elif key == "delete":
            self.pages.pop(idx)
            self.hover_idx = None; self._render()

    # ── 체크박스 전체선택 / 삭제 / 회전 ────────────────────
    def _toggle_all(self):
        if self.chk_var.get(): self.checked = {pg["id"] for pg in self.pages}
        else: self.checked.clear()
        self._render()

    def _delete_checked(self):
        if not self.checked:
            messagebox.showinfo("알림","삭제할 페이지를 선택하세요."); return
        self.pages = [pg for pg in self.pages if pg["id"] not in self.checked]
        self.checked.clear(); self._render()

    def _rotate_checked(self):
        tgt = self.checked or {pg["id"] for pg in self.pages}
        for pg in self.pages:
            if pg["id"] in tgt: pg["rot"]=(pg.get("rot",0)+90)%360
        self._render()

    # ── 파일 관리 ────────────────────────────────────────────
    def _add_files(self):
        ps = filedialog.askopenfilenames(title="PDF 파일 선택",
                                         filetypes=[("PDF","*.pdf")])
        self._load_pdfs(list(ps))

    def _dnd_drop(self, event):
        self.canvas.config(bg=CARD)
        self._load_pdfs([p for p in parse_paths(event.data)
                         if p.lower().endswith(".pdf")])

    def _load_pdfs(self, paths):
        for path in paths:
            try:
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
                                       "annots":[]})
                if fdoc is not None: fdoc.close()
            except Exception as e:
                messagebox.showerror("오류",f"{os.path.basename(path)}\n{e}")
        self._render()

    def _clear(self):
        self.pages.clear(); self.checked.clear()
        self.photos.clear(); self.hover_idx = None; self._render()

    def _open_preview(self, idx):
        if not self.pages: return
        PreviewWin(self.winfo_toplevel(), self.pages, idx,
                   on_change=self._render)   # 편집 후 그리드 자동 갱신

    # ── 내보내기 ────────────────────────────────────────────
    def _export(self):
        if not self.pages:
            messagebox.showwarning("경고","페이지가 없습니다."); return
        init_dir = os.path.dirname(self.pages[0]["src"]) if self.pages else ""
        out = filedialog.asksaveasfilename(title="PDF로 저장",
            defaultextension=".pdf", filetypes=[("PDF","*.pdf")],
            initialdir=init_dir, initialfile="output.pdf")
        if not out: return
        try:
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
            messagebox.showinfo("완료",f"저장 완료!\n{out}")
        except Exception as e:
            messagebox.showerror("오류",str(e))


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
