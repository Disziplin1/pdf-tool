"""
PDF 도구  ·  무료 · 오프라인 · 완전 로컬
  ▸ 정리 탭  : 드래그 정렬 · 체크박스 · 호버 툴바 · 미리보기 + 편집
  ▸ 변환 탭  : PDF → 이미지 / 이미지 → PDF
"""
import sys, os, shutil, subprocess, threading

VERSION = "20260721.1343"                       # 배포.bat 이 자동 업데이트
GITHUB_REPO  = "Disziplin1/pdf-tool"
INSTALL_DIR  = os.path.join(os.environ.get("LOCALAPPDATA", "C:\\Temp"), "PDF편집기")
INSTALL_EXE  = os.path.join(INSTALL_DIR, "PDF 편집기.exe")

# ── 로컬 설치 (첫 실행 시 AppData 에 설치) ──
def _ensure_local():
    if not getattr(sys, "frozen", False):
        return
    cur = os.path.normcase(os.path.abspath(sys.executable))
    dst = os.path.normcase(os.path.abspath(INSTALL_EXE))
    if cur == dst:
        return  # 이미 로컬 설치본에서 실행 중

    os.makedirs(INSTALL_DIR, exist_ok=True)
    shutil.copy2(sys.executable, INSTALL_EXE)

    subprocess.Popen([INSTALL_EXE])
    sys.exit(0)

_ensure_local()

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
                            if a["name"].endswith(".exe")), None)
            if not dl_url:
                return
            root.after(0, lambda: _offer_update(root, latest, dl_url))
        except Exception:
            pass
    threading.Thread(target=_worker, daemon=True).start()

def _offer_update(root, ver, url):
    from tkinter import messagebox as _mb
    if _mb.askyesno("업데이트", f"새 버전 v{ver} 이 있습니다.\n지금 업데이트 하시겠습니까?", parent=root):
        _apply_update(root, url)

def _apply_update(root, url):
    from tkinter import messagebox as _mb
    try:
        import urllib.request
        tmp_exe = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "PDF편집기_update.exe")
        urllib.request.urlretrieve(url, tmp_exe)

        bat = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "pdf_update.bat")
        with open(bat, "w", encoding="cp949") as f:
            f.write("@echo off\n")
            f.write("timeout /t 2 /nobreak >nul\n")
            f.write(f'copy /y "{tmp_exe}" "{INSTALL_EXE}"\n')
            f.write(f'start "" "{INSTALL_EXE}"\n')
            f.write('del "%~f0"\n')
        subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000)
        root.destroy()
    except Exception as e:
        _mb.showerror("업데이트 오류", str(e), parent=root)

import tkinter as tk
from tkinter import filedialog, messagebox
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
#  아이폰 글래스 테마
# ══════════════════════════════════════════════════════════
BG       = "#ede8f8"   # 연보라 배경
PANEL    = "#fafbff"   # 패널
TOOLBAR  = "#f4f0fc"   # 툴바 (frosted)
CARD     = "#ffffff"   # 카드
CARD_CHK = "#ede6ff"   # 선택 카드
ACCENT   = "#7928ca"   # iOS 보라
ACCENT_L = "#9b4fdf"   # 밝은 보라
TEXT     = "#1a0840"   # 진한 보라-검정
TEXT_DIM = "#9070b8"   # 보조
BORDER   = "#e2d8f4"   # 테두리
SUCCESS  = "#30d158"   # iOS 초록
DANGER   = "#ff3b30"   # iOS 빨강
DROPH    = "#e4d8ff"   # 드래그오버
INSLINE  = "#7928ca"
SH1      = "#c8bce0"   # 그림자 (진)
SH2      = "#ddd4f0"   # 그림자 (연)
PREV_BG  = "#140830"   # 미리보기 배경

FM     = "맑은 고딕"
FONT   = (FM, 10)
FONT_B = (FM, 10, "bold")
FONT_H = (FM, 14, "bold")
FONT_S = (FM, 9)
FONT_XS= (FM, 8)


# ══════════════════════════════════════════════════════════
#  공용 유틸
# ══════════════════════════════════════════════════════════
def mkbtn(p, txt, cmd, bg=ACCENT, fg="white", px=12, py=6, **kw):
    hl = ACCENT_L if bg == ACCENT else bg
    b  = tk.Button(p, text=txt, command=cmd, bg=bg, fg=fg,
                   font=FONT_B, relief="flat", cursor="hand2",
                   padx=px, pady=py, bd=0, **kw)
    b.bind("<Enter>", lambda e: b.config(bg=hl))
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


def make_thumb(path, pidx, tw, th):
    if not PREVIEW_OK: return None
    try:
        doc  = fitz.open(path)
        if pidx >= len(doc): return None
        page = doc[pidx]
        sc   = min(tw/page.rect.width, th/page.rect.height) * 2
        pix  = page.get_pixmap(matrix=fitz.Matrix(sc, sc), alpha=False)
        img  = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img.thumbnail((tw, th), Image.LANCZOS)
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
#  미리보기 창  (크게보기 + 편집: 삭제·회전)
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

        self.bind("<Left>",       lambda e: self._go(-1))
        self.bind("<Right>",      lambda e: self._go(1))
        self.bind("<Escape>",     lambda e: self.destroy())
        self.bind("<plus>",       lambda e: self._zoom(1.25))
        self.bind("<equal>",      lambda e: self._zoom(1.25))
        self.bind("<minus>",      lambda e: self._zoom(1/1.25))
        self.bind("<0>",          lambda e: self._zoom_reset())

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

        # ── 이미지 캔버스 ─────────────────────────────────
        cf = tk.Frame(self, bg=PREV_BG)
        cf.pack(fill="both", expand=True, padx=30, pady=12)
        self.canvas = tk.Canvas(cf, bg=PREV_BG, bd=0, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>",      self._on_resize)
        self.canvas.bind("<MouseWheel>",
                         lambda e: self._zoom(1.15 if e.delta > 0 else 1/1.15))
        self.canvas.bind("<ButtonPress-1>",  self._drag_start)
        self.canvas.bind("<B1-Motion>",      self._drag_move)
        self.canvas.bind("<ButtonRelease-1>",self._drag_end)

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
            base_sc = min(cw*0.86/page.rect.width, ch*0.90/page.rect.height)
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
        except Exception as e:
            self.canvas.create_text(cw//2, ch//2, text=f"오류:\n{e}",
                                    fill="#a88", font=FONT, justify="center")

    def _go(self, d):
        if 0 <= self.idx+d < len(self.pages):
            self.idx += d
            self.pan_x = 0; self.pan_y = 0   # 페이지 바뀌면 위치 초기화
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

    # ── 드래그 이동 ──────────────────────────────────────────
    def _drag_start(self, e):
        self._drag_sx = e.x
        self._drag_sy = e.y
        self.canvas.config(cursor="fleur")   # 십자 이동 커서

    def _drag_move(self, e):
        if self._drag_sx is None: return
        self.pan_x += e.x - self._drag_sx
        self.pan_y += e.y - self._drag_sy
        self._drag_sx = e.x
        self._drag_sy = e.y
        self._show()

    def _drag_end(self, e):
        self._drag_sx = None
        self._drag_sy = None
        self.canvas.config(cursor="")

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
        self.scale     = 1.0
        self.drag_src  = None
        self.drag_tgt  = None
        self.drag_moved= False
        self.hover_idx = None
        self._rid      = None
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
        tb = tk.Frame(self, bg=TOOLBAR, pady=6)
        tb.pack(fill="x")

        mkbtn(tb, "+ 파일 추가", self._add_files).pack(side="left", padx=(12,4))
        sep_v(tb)

        self.chk_var = tk.BooleanVar()
        tk.Checkbutton(tb, variable=self.chk_var, command=self._toggle_all,
                       text="전체선택", bg=TOOLBAR, fg=TEXT, selectcolor=ACCENT,
                       activebackground=TOOLBAR, font=FONT_S,
                       bd=0, highlightthickness=0).pack(side="left", padx=4)

        mkbtn(tb, "선택 삭제", self._delete_checked, bg=DANGER, py=5).pack(side="left", padx=4)
        mkbtn(tb, "전체 삭제", self._clear,           bg=DANGER, py=5).pack(side="left", padx=4)
        sep_v(tb)
        mkbtn(tb, "↺ 선택 회전", self._rotate_checked, bg=TOOLBAR,
              fg=TEXT, py=5).pack(side="left", padx=4)

        mkbtn(tb, "▶  PDF 내보내기", self._export, bg=SUCCESS).pack(side="right", padx=(4,12))
        sep_v(tb)
        mkbtn(tb, "+", lambda: self._zoom(1.18), bg=TOOLBAR, fg=TEXT, px=8, py=5).pack(side="right", padx=2)
        mkbtn(tb, "−", lambda: self._zoom(0.85), bg=TOOLBAR, fg=TEXT, px=8, py=5).pack(side="right", padx=2)
        self.info_lbl = tk.Label(tb, text="", font=FONT_S, bg=TOOLBAR, fg=TEXT_DIM)
        self.info_lbl.pack(side="right", padx=10)

        self.hint = tk.Label(self,
            text="PDF 파일을 여기로 끌어다 놓으세요\n"
                 "여러 파일 동시 추가  ·  드래그로 순서 변경  ·  🔍 버튼으로 미리보기",
            font=FONT, bg=BG, fg=TEXT_DIM, justify="center")
        self.hint.pack(pady=60)

        cf = tk.Frame(self, bg=BG)
        cf.pack(fill="both", expand=True)
        vs = tk.Scrollbar(cf, orient="vertical", bg=TOOLBAR, troughcolor=BG)
        vs.pack(side="right", fill="y")
        self.canvas = tk.Canvas(cf, bg=BG, bd=0, highlightthickness=0,
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

        if DND_OK:
            for w in (self, self.canvas, self.hint):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<DragEnter>>", lambda e: self.canvas.config(bg=DROPH))
                w.dnd_bind("<<DragLeave>>", lambda e: self.canvas.config(bg=BG))
                w.dnd_bind("<<Drop>>",      self._dnd_drop)

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
            self.hint.pack(pady=60)
            self.info_lbl.config(text=""); return

        self.hint.pack_forget()
        cols    = self._cols()
        rows    = (n+cols-1)//cols
        total_h = self.PAD + rows*(self.CH+self.PAD)
        cw      = max(self.canvas.winfo_width(), 1)
        self.canvas.configure(scrollregion=(0,0,cw,max(total_h,self.canvas.winfo_height())))

        for i, pg in enumerate(self.pages):
            x0, y0 = self._card_xy(i)
            self._draw_card(i, x0, y0, pg)

        if insert_at is not None:
            cols2 = self._cols()
            col   = min(insert_at%cols2, cols2-1)
            row   = insert_at//cols2
            lx    = self.PAD + col*(self.CW+self.PAD) - self.PAD//2
            ly0   = self.PAD + row*(self.CH+self.PAD) - 4
            self.canvas.create_line(lx, ly0, lx, ly0+self.CH+8,
                                    fill=INSLINE, width=3, tags="ins")

        if self.hover_idx is not None and self.hover_idx < n:
            self._draw_hover_ol(self.hover_idx)

        nc = len(self.checked)
        self.info_lbl.config(text=f"{n}페이지  |  {nc}개 선택")
        self.chk_var.set(n > 0 and nc == n)

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
        for d, col in [(6,SH1),(4,SH2),(2,"#eee8f8")]:
            rr(self.canvas, x0+d, y0+d, x0+self.CW+d, y0+self.CH+d,
               r=14, fill=col, outline="", tags=(tag,"shadow"))

        # ── 카드 배경 (둥근 모서리) ─────────────────────
        card_fill = CARD_CHK if chk else CARD
        card_bd   = ACCENT   if chk else BORDER
        rr(self.canvas, x0, y0, x0+self.CW, y0+self.CH,
           r=14, fill=card_fill, outline=card_bd,
           width=2 if chk else 1, tags=(tag,"card"))

        # ── 썸네일 영역 배경 (연보라 tint) ──────────────
        rr(self.canvas, x0+1, y0+1, x0+self.CW-1, y0+img_h,
           r=14, fill="#f5f0ff", outline="", tags=(tag,"card"))

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
                fill="#ddd8ee", outline="", tags=(tag,"card"))
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
                fill="white", outline="#b8a8d8", width=1.5, tags=(tag,cbt,"cb"))

    # ── 호버 오버레이 ────────────────────────────────────────
    def _draw_hover_ol(self, idx):
        if idx >= len(self.pages): return
        x0, y0 = self._card_xy(idx)
        bbar   = self.BBAR_H
        bar_y  = y0 + self.CH - bbar

        # 보라 테두리 (카드 전체)
        rr(self.canvas, x0-3, y0-3, x0+self.CW+3, y0+self.CH+3,
           r=16, fill="", outline=ACCENT, width=3, tags="hov")

        # 하단 바를 보라 그라데이션처럼
        rr(self.canvas, x0+1, bar_y+1, x0+self.CW-1, y0+self.CH-1,
           r=0, fill=ACCENT, outline="", tags="hov")
        # 아래 모서리만 둥글게
        rr(self.canvas, x0+1, bar_y+1, x0+self.CW-1, y0+self.CH-1,
           r=13, fill=ACCENT, outline="", tags="hov")

        # 버튼 그리기  ← tag_bind 없이 _on_press 에서만 처리
        by = bar_y + bbar//2
        r  = min(13, bbar//2 - 4)
        btn_styles = {
            "preview": ("#ffffff", ACCENT,    ACCENT),
            "rotate":  ("#e8d8ff", ACCENT_L,  ACCENT),
            "dup":     ("#dde8ff", "#4488cc",  "#3366bb"),
            "delete":  (DANGER,   "#ff8070",  "white"),
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

    def _on_hover(self, event):
        if self.drag_src is not None: return
        cx  = self.canvas.canvasx(event.x)
        cy  = self.canvas.canvasy(event.y)
        idx = self._xy_to_card(cx, cy)
        if idx != self.hover_idx:
            self.canvas.delete("hov")
            self.hover_idx = idx
            if idx is not None: self._draw_hover_ol(idx)

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
        self.drag_moved = True
        cx  = self.canvas.canvasx(event.x)
        cy  = self.canvas.canvasy(event.y)
        tgt = self._xy_to_insert(cx, cy)
        if tgt != self.drag_tgt:
            self.drag_tgt = tgt; self._render(insert_at=tgt)
        h = self.canvas.winfo_height()
        if event.y < 50:     self.canvas.yview_scroll(-1,"units")
        elif event.y > h-50: self.canvas.yview_scroll( 1,"units")

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
        self.canvas.config(bg=BG)
        self._load_pdfs([p for p in parse_paths(event.data)
                         if p.lower().endswith(".pdf")])

    def _load_pdfs(self, paths):
        for path in paths:
            try:
                r = PdfReader(path)
                for pidx in range(len(r.pages)):
                    pil = make_thumb(path, pidx, self.TW0, self.TH0)
                    self.pages.append({"id":next(_id_gen),"src":path,
                                       "pidx":pidx,"pil":pil,"rot":0})
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
        self.img_hover      = None
        self.img_drag_src   = None
        self.img_drag_tgt   = None
        self.img_drag_moved = False
        self.out_name       = tk.StringVar(value="")
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

        # ── 미리보기 캔버스 ─────────────────────────────────
        cf = tk.Frame(self, bg=BG); cf.pack(fill="both", expand=True, padx=20)
        pvs = tk.Scrollbar(cf, orient="vertical", bg=TOOLBAR, troughcolor=BG)
        pvs.pack(side="right", fill="y")
        self.pcanvas = tk.Canvas(cf, bg=BG, bd=1, relief="solid",
                                 highlightthickness=0, yscrollcommand=pvs.set)
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

        # 저장 버튼
        self.dl_btn = mkbtn(inner, "▼  저장하기", self._do_save, px=36, py=10)
        self.dl_btn.pack(pady=(4,2))

        self._reset()

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
        self.status_lbl.config(text=f"📄  PDF  ·  {n}페이지  →  PNG 이미지로 변환 (최고 화질)")
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
            self.status_lbl.config(text=f"🖼  이미지  ·  {n}개  →  PDF로 변환")
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
        self.status_lbl.config(text="")
        self.reset_btn.pack_forget()
        self.dl_btn.config(state="disabled", bg="#b8a8d8")
        self.pcanvas.delete("all")
        self.pcanvas.after(80, self._draw_hint)

    def _draw_hint(self):
        self.pcanvas.delete("all")
        cw = max(self.pcanvas.winfo_width(), 200)
        ch = max(self.pcanvas.winfo_height(), 100)
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
        cols    = self._img_cols()
        rows    = (n+cols-1)//cols
        total_h = self.IPAD + rows*(self.ICH+self.IPAD)
        cw      = max(self.pcanvas.winfo_width(), 1)
        self.pcanvas.configure(
            scrollregion=(0,0,cw,max(total_h,self.pcanvas.winfo_height())))
        for i, (thumb, label) in enumerate(zip(items, labels)):
            x0, y0 = self._img_card_xy(i)
            self._draw_card(i, x0, y0, thumb, label)
        if insert_at is not None and self.mode == "img2pdf":
            cols2 = self._img_cols()
            col   = min(insert_at%cols2, cols2-1)
            row   = insert_at//cols2
            lx    = self.IPAD + col*(self.ICW+self.IPAD) - self.IPAD//2
            ly0   = self.IPAD + row*(self.ICH+self.IPAD) - 4
            self.pcanvas.create_line(lx, ly0, lx, ly0+self.ICH+8,
                                     fill=INSLINE, width=3, tags="iins")
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
           r=12, fill="#f5f0ff", outline="", tags=(tag,"card"))
        if PREVIEW_OK and thumb:
            sc  = min((self.ICW-16)/thumb.width, (lby-y0-16)/thumb.height)
            nw  = max(1, int(thumb.width*sc))
            nh  = max(1, int(thumb.height*sc))
            img = thumb.resize((nw, nh), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.img_photos.append(photo)
            icy = y0+(lby-y0)//2
            self.pcanvas.create_rectangle(cx2-nw//2-2,icy-nh//2-2,cx2+nw//2+2,icy+nh//2+2,
                fill="#ddd8ee", outline="", tags=(tag,"card"))
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

    def _img_on_hover(self, event):
        if self.mode != "img2pdf" or self.img_drag_src is not None: return
        cx = self.pcanvas.canvasx(event.x)
        cy = self.pcanvas.canvasy(event.y)
        idx = self._xy_to_card(cx, cy)
        if idx != self.img_hover:
            self.pcanvas.delete("ihov")
            self.img_hover = idx
            if idx is not None: self._draw_hover(idx)

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
        self.img_drag_moved = True
        cx = self.pcanvas.canvasx(event.x)
        cy = self.pcanvas.canvasy(event.y)
        tgt = self._xy_to_insert(cx, cy)
        if tgt != self.img_drag_tgt:
            self.img_drag_tgt = tgt; self._render_preview(insert_at=tgt)
        h = self.pcanvas.winfo_height()
        if event.y < 40:     self.pcanvas.yview_scroll(-1,"units")
        elif event.y > h-40: self.pcanvas.yview_scroll( 1,"units")

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
                self.status_lbl.config(
                    text=f"🖼  이미지  ·  {len(self.img_files)}개  →  PDF로 변환")
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
        self._build()
        self.after(3000, lambda: _check_update(self))  # 3초 후 백그라운드 업데이트 확인

    def _build(self):
        # 헤더 (글래스 느낌)
        hdr = tk.Frame(self, bg=PANEL)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  PDF 편집기", font=(FM,13,"bold"),
                 bg=PANEL, fg=TEXT).pack(side="left", pady=12)
        flags = []
        if PREVIEW_OK: flags.append("미리보기 ✓")
        if DND_OK:     flags.append("드래그앤드롭 ✓")
        tk.Label(hdr, text="  ·  ".join(flags),
                 font=FONT_S, bg=PANEL, fg=TEXT_DIM).pack(side="left", padx=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        tb = tk.Frame(self, bg=BG)
        tb.pack(fill="x", padx=16, pady=8)
        self.tabs = {}; self.tbtns = {}

        for key,lbl in [("organize","정리  (병합 · 분할)"),("convert","변환  (PDF ↔ 이미지)")]:
            b = tk.Button(tb, text=lbl, font=FONT_B, bg=ACCENT, fg="white",
                          relief="flat", padx=18, pady=9, bd=0, cursor="hand2",
                          command=lambda k=key: self._sw(k))
            b.pack(side="left", padx=(0,4)); self.tbtns[key] = b

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        cont = tk.Frame(self, bg=BG); cont.pack(fill="both", expand=True)
        self.tabs["organize"] = OrganizeTab(cont)
        self.tabs["convert"]  = ConvertTab(cont)
        self._sw("organize")

    def _sw(self, key):
        for f in self.tabs.values(): f.pack_forget()
        self.tabs[key].pack(fill="both", expand=True)
        for k,b in self.tbtns.items():
            b.config(bg=ACCENT if k==key else "#d4c8f0",
                     fg="white" if k==key else TEXT)


if __name__ == "__main__":
    App().mainloop()
