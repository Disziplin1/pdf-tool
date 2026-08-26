"""
pdf_tool.py 자동 테스트 (unittest, 표준 라이브러리만 사용)

실행 방법 (Tkinter GUI 를 실제로 생성하므로 디스플레이가 필요):
    xvfb-run -a python -m unittest test_pdf_tool.py -v

테스트 대상:
  - 좌표 변환 함수 (mm/pt, 회전, 화면<->PDF) 는 순수 함수 테스트
  - OrganizeTab/PreviewWin 은 실제 Tk 위젯을 만들어 동작을 검증
  - 모달 입력창(simpledialog)은 실제로 띄우지 않고 PreviewWin._ask_text 를
    mock 처리해서 테스트를 자동으로 진행한다 (지시사항 22번 참고)
"""
import math
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import fitz  # PyMuPDF — 테스트용 PDF 생성 및 pdf_tool 내부에서도 사용

import pdf_tool as pt


class FakeEvent:
    def __init__(self, x=0, y=0, delta=0):
        self.x = x
        self.y = y
        self.delta = delta


def make_pdf(path, sizes=((595.28, 841.89), (420, 300))):
    """sizes 에 지정된 (w_pt, h_pt) 페이지들로 구성된 간단한 PDF 생성."""
    doc = fitz.open()
    for w, h in sizes:
        doc.new_page(width=w, height=h)
    doc.save(path)
    doc.close()


# ══════════════════════════════════════════════════════════
#  1. 좌표 변환 함수 — 순수 함수, GUI 불필요
# ══════════════════════════════════════════════════════════
class TestCoordMath(unittest.TestCase):
    def test_mm_pt_roundtrip(self):
        for mm in [0, 1, 25.4, 100, 210, 297]:
            self.assertAlmostEqual(pt.pt_to_mm(pt.mm_to_pt(mm)), mm, places=9)

    def test_mm_to_pt_known_values(self):
        # 25.4mm == 1 inch == 72pt
        self.assertAlmostEqual(pt.mm_to_pt(25.4), 72.0, places=6)
        self.assertAlmostEqual(pt.pt_to_mm(72.0), 25.4, places=6)

    def test_rotate_unrotate_roundtrip_all_angles(self):
        w, h = 595.0, 842.0
        points = [(0, 0), (w, 0), (0, h), (w, h), (123.4, 456.7), (w/2, h/2)]
        for rot in (0, 90, 180, 270):
            for x, y in points:
                rx, ry = pt.rotate_point_pt(x, y, w, h, rot)
                bx, by = pt.unrotate_point_pt(rx, ry, w, h, rot)
                self.assertAlmostEqual(bx, x, places=6, msg=f"rot={rot} x")
                self.assertAlmostEqual(by, y, places=6, msg=f"rot={rot} y")

    def test_rotate_known_corners_90(self):
        w, h = 200.0, 100.0
        # 원본 좌상단(0,0) 은 시계방향 90도 회전 후 새 이미지의 우상단으로 이동해야 함
        rx, ry = pt.rotate_point_pt(0, 0, w, h, 90)
        rw, rh = pt.rotated_size_pt(w, h, 90)
        self.assertAlmostEqual(rx, rw)
        self.assertAlmostEqual(ry, 0)

    def test_rotated_size(self):
        self.assertEqual(pt.rotated_size_pt(200, 100, 0), (200, 100))
        self.assertEqual(pt.rotated_size_pt(200, 100, 90), (100, 200))
        self.assertEqual(pt.rotated_size_pt(200, 100, 180), (200, 100))
        self.assertEqual(pt.rotated_size_pt(200, 100, 270), (100, 200))

    def test_pdf_screen_roundtrip(self):
        w, h = 595.0, 842.0
        for rot in (0, 90, 180, 270):
            for scale in (0.5, 1.0, 2.3):
                for x, y in [(0, 0), (w, h), (100, 200), (w/2, h/2)]:
                    px, py = pt.pdf_to_screen(x, y, w, h, rot, scale, cx=500, cy=400)
                    bx, by = pt.screen_to_pdf(px, py, w, h, rot, scale, cx=500, cy=400)
                    self.assertAlmostEqual(bx, x, places=6)
                    self.assertAlmostEqual(by, y, places=6)

    def test_screen_position_changes_with_zoom_but_pdf_coord_is_input_invariant(self):
        # 같은 PDF 좌표라도 scale(줌)이 다르면 화면 좌표는 달라져야 하고,
        # screen_to_pdf 로 되돌리면 항상 같은 PDF 좌표가 나와야 한다.
        w, h = 595.0, 842.0
        x, y = 100.0, 150.0
        p1 = pt.pdf_to_screen(x, y, w, h, 0, 1.0, 0, 0)
        p2 = pt.pdf_to_screen(x, y, w, h, 0, 2.0, 0, 0)
        self.assertNotEqual(p1, p2)
        for scale, p in [(1.0, p1), (2.0, p2)]:
            bx, by = pt.screen_to_pdf(p[0], p[1], w, h, 0, scale, 0, 0)
            self.assertAlmostEqual(bx, x, places=6)
            self.assertAlmostEqual(by, y, places=6)


# ══════════════════════════════════════════════════════════
#  2. OrganizeTab — 페이지 데이터/기존 기능 회귀 테스트
# ══════════════════════════════════════════════════════════
class TestOrganizeTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = pt.TkinterDnD.Tk() if pt.DND_OK else pt.tk.Tk()
        cls.root.withdraw()
        cls.tmpdir = tempfile.mkdtemp(prefix="pdftool_test_")
        cls.pdf_path = os.path.join(cls.tmpdir, "sample.pdf")
        make_pdf(cls.pdf_path)  # 2페이지: A4, 420x300pt

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _new_tab_with_pdf(self):
        ot = pt.OrganizeTab(self.root)
        ot._load_pdfs([self.pdf_path])
        return ot

    def test_load_pdf_sets_page_dims_and_annots(self):
        ot = self._new_tab_with_pdf()
        self.assertEqual(len(ot.pages), 2)
        p0, p1 = ot.pages
        self.assertAlmostEqual(p0["page_w_pt"], 595.28, places=1)
        self.assertAlmostEqual(p0["page_h_pt"], 841.89, places=1)
        self.assertAlmostEqual(p1["page_w_pt"], 420.0, places=1)
        self.assertAlmostEqual(p1["page_h_pt"], 300.0, places=1)
        self.assertEqual(p0["annots"], [])
        self.assertEqual(p1["annots"], [])
        self.assertEqual(p0["rot"], 0)

    def test_page_rotate(self):
        ot = self._new_tab_with_pdf()
        self.assertEqual(ot.pages[0]["rot"], 0)
        ot._hov_action("rotate", 0)
        self.assertEqual(ot.pages[0]["rot"], 90)
        ot._hov_action("rotate", 0)
        self.assertEqual(ot.pages[0]["rot"], 180)

    def test_page_delete(self):
        ot = self._new_tab_with_pdf()
        self.assertEqual(len(ot.pages), 2)
        ot._hov_action("delete", 0)
        self.assertEqual(len(ot.pages), 1)

    def test_page_duplicate_annots_are_independent(self):
        """복제 시 annots 리스트가 원본과 공유되면 안 된다 (얕은 복사 버그 회귀)."""
        ot = self._new_tab_with_pdf()
        ot.pages[0]["annots"].append({"id": 999, "type": "text", "text": "orig", "x": 1, "y": 1})
        ot._hov_action("dup", 0)
        self.assertEqual(len(ot.pages), 3)
        orig, dup = ot.pages[0], ot.pages[1]
        self.assertIsNot(orig["annots"], dup["annots"])
        # 복제본의 annot 을 수정해도 원본은 영향을 받지 않아야 함
        dup["annots"][0]["text"] = "changed"
        self.assertEqual(orig["annots"][0]["text"], "orig")
        # 복제본에 새 annot 을 추가해도 원본 리스트 길이는 그대로여야 함
        dup["annots"].append({"id": 1000, "type": "text", "text": "new", "x": 0, "y": 0})
        self.assertEqual(len(orig["annots"]), 1)
        self.assertEqual(len(dup["annots"]), 2)

    def test_page_reorder(self):
        ot = self._new_tab_with_pdf()
        ids_before = [p["id"] for p in ot.pages]
        ot.drag_src = 0
        ot.drag_tgt = 2  # 맨 뒤로 이동
        ot.drag_moved = True
        ot._on_release(FakeEvent())
        ids_after = [p["id"] for p in ot.pages]
        self.assertEqual(ids_after, [ids_before[1], ids_before[0]])

    def test_export_produces_pdf_with_expected_pages(self):
        ot = self._new_tab_with_pdf()
        out_path = os.path.join(self.tmpdir, "out.pdf")
        with patch.object(pt.filedialog, "asksaveasfilename", return_value=out_path), \
             patch.object(pt.messagebox, "showinfo"):
            ot._export()
        self.assertTrue(os.path.isfile(out_path))
        from pypdf import PdfReader
        r = PdfReader(out_path)
        self.assertEqual(len(r.pages), 2)


# ══════════════════════════════════════════════════════════
#  3. PreviewWin — Phase 3 텍스트 기본 기능 (생성/표시/선택/이동/삭제)
# ══════════════════════════════════════════════════════════
class TestPreviewWinText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = pt.TkinterDnD.Tk() if pt.DND_OK else pt.tk.Tk()
        cls.root.withdraw()
        cls.tmpdir = tempfile.mkdtemp(prefix="pdftool_test_")
        cls.pdf_path = os.path.join(cls.tmpdir, "sample.pdf")
        make_pdf(cls.pdf_path)

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _make_pages(self):
        ot = pt.OrganizeTab(self.root)
        ot._load_pdfs([self.pdf_path])
        return ot.pages

    def _open_preview(self, pages, start=0):
        pw = pt.PreviewWin(self.root, pages, start)
        pw.update_idletasks()
        pw.geometry("900x800+0+0")
        pw.update_idletasks()
        pw._show()  # after() 타이머를 기다리지 않고 즉시 렌더링
        self.addCleanup(pw.destroy)
        return pw

    def test_initial_mode_is_view_not_edit(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self.assertFalse(pw.edit_mode)
        self.assertFalse(pw.edit_toolbar.winfo_ismapped())

    def test_toggle_edit_shows_toolbar(self):
        # winfo_ismapped() 는 창 관리자(WM) 유무에 좌우될 수 있어, 실제로
        # pack 되어 있는지는 geometry manager 상태(pack_slaves)로 확인한다.
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._toggle_edit()
        self.assertTrue(pw.edit_mode)
        pw.update_idletasks()
        self.assertIn(pw.edit_toolbar, pw.edit_toolbar.master.pack_slaves())
        pw._toggle_edit()
        pw.update_idletasks()
        self.assertNotIn(pw.edit_toolbar, pw.edit_toolbar.master.pack_slaves())

    def test_create_text_stores_pdf_pt_coords(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self.assertIsNotNone(pw._sc, "렌더링이 성공해서 좌표 변환 상태가 설정되어야 함")
        pw._toggle_edit()
        pw._set_tool("text")

        click_x, click_y = 300, 300
        with patch.object(pt.PreviewWin, "_ask_text", return_value="안녕하세요"):
            pw._on_canvas_press(FakeEvent(x=click_x, y=click_y))

        annots = pages[0]["annots"]
        self.assertEqual(len(annots), 1)
        a = annots[0]
        self.assertEqual(a["type"], "text")
        self.assertEqual(a["text"], "안녕하세요")

        # 저장된 좌표가 PDF pt 공간이며, 클릭 지점을 screen_to_pdf 로 변환한 값과 일치해야 함
        expect_x, expect_y = pt.screen_to_pdf(
            click_x, click_y, pw._cur_pw, pw._cur_ph, pw._cur_rot, pw._sc, pw._cx, pw._cy)
        self.assertAlmostEqual(a["x"], expect_x, places=4)
        self.assertAlmostEqual(a["y"], expect_y, places=4)

    def test_created_text_is_drawn_on_canvas(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._toggle_edit(); pw._set_tool("text")
        with patch.object(pt.PreviewWin, "_ask_text", return_value="hi"):
            pw._on_canvas_press(FakeEvent(x=250, y=250))
        aid = pages[0]["annots"][0]["id"]
        items = pw.canvas.find_withtag(f"annot_{aid}")
        self.assertTrue(len(items) >= 1)

    def test_empty_text_input_cancelled(self):
        """입력창에서 취소(None)하면 annot 이 생성되지 않아야 한다."""
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._toggle_edit(); pw._set_tool("text")
        with patch.object(pt.PreviewWin, "_ask_text", return_value=None):
            pw._on_canvas_press(FakeEvent(x=250, y=250))
        self.assertEqual(pages[0]["annots"], [])

    def test_select_text(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._toggle_edit(); pw._set_tool("text")
        with patch.object(pt.PreviewWin, "_ask_text", return_value="select-me"):
            pw._on_canvas_press(FakeEvent(x=300, y=300))
        aid = pages[0]["annots"][0]["id"]
        # Phase 4: 새로 만든 텍스트는 즉시 선택되어 속성 패널이 바로 뜬다
        # (X/Y를 바로 mm 로 입력할 수 있어야 하므로).
        self.assertEqual(pw.selected_id, aid)

        pw._select_annot(None)
        self.assertIsNone(pw.selected_id)
        pw._set_tool("select")
        pw._on_canvas_press(FakeEvent(x=300, y=300))
        self.assertEqual(pw.selected_id, aid)

    def test_move_text_updates_pdf_coords_and_survives_zoom(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._toggle_edit(); pw._set_tool("text")
        with patch.object(pt.PreviewWin, "_ask_text", return_value="move-me"):
            pw._on_canvas_press(FakeEvent(x=300, y=300))
        annot = pages[0]["annots"][0]
        x_before, y_before = annot["x"], annot["y"]

        # 선택 후 드래그로 이동
        pw._set_tool("select")
        pw._on_canvas_press(FakeEvent(x=300, y=300))
        self.assertIsNotNone(pw._move_state)
        pw._on_canvas_motion(FakeEvent(x=340, y=360))
        pw._on_canvas_release(FakeEvent(x=340, y=360))

        self.assertNotEqual((annot["x"], annot["y"]), (x_before, y_before))

        # 줌을 바꿔도 저장된 PDF pt 좌표 자체는 변하면 안 됨
        x_after_move, y_after_move = annot["x"], annot["y"]
        pw._zoom(1.4)
        self.assertEqual(annot["x"], x_after_move)
        self.assertEqual(annot["y"], y_after_move)

    def test_delete_selected_text(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._toggle_edit(); pw._set_tool("text")
        with patch.object(pt.PreviewWin, "_ask_text", return_value="delete-me"):
            pw._on_canvas_press(FakeEvent(x=280, y=280))
        self.assertEqual(len(pages[0]["annots"]), 1)

        pw._set_tool("select")
        pw._on_canvas_press(FakeEvent(x=280, y=280))
        self.assertIsNotNone(pw.selected_id)
        pw._delete_selected_annot()
        self.assertEqual(pages[0]["annots"], [])
        self.assertIsNone(pw.selected_id)

    def test_pages_are_independent(self):
        pages = self._make_pages()
        pw = self._open_preview(pages, start=0)
        pw._toggle_edit(); pw._set_tool("text")
        with patch.object(pt.PreviewWin, "_ask_text", return_value="page0-text"):
            pw._on_canvas_press(FakeEvent(x=300, y=300))
        self.assertEqual(len(pages[0]["annots"]), 1)
        self.assertEqual(len(pages[1]["annots"]), 0)

        pw._go(1)
        self.assertEqual(pw.idx, 1)
        self.assertIsNone(pw.selected_id)
        with patch.object(pt.PreviewWin, "_ask_text", return_value="page1-text"):
            pw._on_canvas_press(FakeEvent(x=200, y=200))
        self.assertEqual(len(pages[0]["annots"]), 1)
        self.assertEqual(len(pages[1]["annots"]), 1)
        self.assertNotEqual(pages[0]["annots"][0]["text"], pages[1]["annots"][0]["text"])

    def test_rotation_roundtrip_for_each_angle(self):
        """0/90/180/270 각각에서, 화면 클릭 위치 -> PDF 좌표 -> 화면 위치가 일치해야 함."""
        pages = self._make_pages()
        pw = self._open_preview(pages)
        for rot in (0, 90, 180, 270):
            pages[0]["rot"] = rot
            pw._show()
            self.assertIsNotNone(pw._sc)
            click = (310, 260)
            x_pt, y_pt = pt.screen_to_pdf(click[0], click[1], pw._cur_pw, pw._cur_ph,
                                           pw._cur_rot, pw._sc, pw._cx, pw._cy)
            back = pt.pdf_to_screen(x_pt, y_pt, pw._cur_pw, pw._cur_ph,
                                     pw._cur_rot, pw._sc, pw._cx, pw._cy)
            self.assertAlmostEqual(back[0], click[0], places=4, msg=f"rot={rot}")
            self.assertAlmostEqual(back[1], click[1], places=4, msg=f"rot={rot}")

    # ── 기존 기능 회귀 (미리보기 창) ──────────────────────────
    def test_existing_zoom_and_pan_still_work(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self.assertEqual(pw.zoom, 1.0)
        pw._zoom(1.25)
        self.assertAlmostEqual(pw.zoom, 1.25)
        pw._zoom_reset()
        self.assertEqual(pw.zoom, 1.0)
        self.assertEqual(pw.pan_x, 0)

    def test_existing_rotate_and_delete_buttons_still_work(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._rotate(90)
        self.assertEqual(pages[0]["rot"], 90)
        n_before = len(pages)
        with patch.object(pt.messagebox, "askyesno", return_value=True):
            pw._delete()
        self.assertEqual(len(pages), n_before - 1)


# ══════════════════════════════════════════════════════════
#  4. Phase 4 — 텍스트 속성 패널 (X/Y mm 입력, 글꼴/크기/색상/굵게/
#     기울임/정렬/회전)
# ══════════════════════════════════════════════════════════
class TestPropertyPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = pt.TkinterDnD.Tk() if pt.DND_OK else pt.tk.Tk()
        cls.root.withdraw()
        cls.tmpdir = tempfile.mkdtemp(prefix="pdftool_test_")
        cls.pdf_path = os.path.join(cls.tmpdir, "sample.pdf")
        make_pdf(cls.pdf_path)  # 2페이지: A4, 420x300pt

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _make_pages(self):
        ot = pt.OrganizeTab(self.root)
        ot._load_pdfs([self.pdf_path])
        return ot.pages

    def _open_preview_with_text(self, pages, click=(300, 300), start=0):
        pw = pt.PreviewWin(self.root, pages, start)
        pw.update_idletasks()
        pw.geometry("900x800+0+0")
        pw.update_idletasks()
        pw._show()
        self.addCleanup(pw.destroy)
        pw._toggle_edit()
        pw._set_tool("text")
        with patch.object(pt.PreviewWin, "_ask_text", return_value="원본텍스트"):
            pw._on_canvas_press(FakeEvent(x=click[0], y=click[1]))
        annot = pages[start]["annots"][0]
        self.assertEqual(pw.selected_id, annot["id"])  # 생성 직후 자동 선택
        return pw, annot

    # ── mm <-> pt 왕복 ────────────────────────────────────────
    def test_xy_input_mm_stored_as_pt_and_redisplayed(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel

        panel.x_var.set("125.00")
        panel.y_var.set("35.00")
        panel._apply_xy()

        self.assertAlmostEqual(annot["x"], pt.mm_to_pt(125.00), places=6)
        self.assertAlmostEqual(annot["y"], pt.mm_to_pt(35.00), places=6)
        # 다시 표시했을 때 0.01mm 정밀도로 원래 값이 보여야 함
        self.assertEqual(panel.x_var.get(), "125.00")
        self.assertEqual(panel.y_var.get(), "35.00")

    def test_xy_display_rounds_but_internal_value_keeps_precision(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        # 반올림했을 때 "125.00" 으로 보이지만 내부값은 그보다 더 정밀해야 하는
        # 예: 125.004 mm 입력 -> 표시는 125.00 이지만 pt 값은 125.004mm 기준이어야 함
        panel.x_var.set("125.004")
        panel.y_var.set("35.006")
        panel._apply_xy()
        self.assertEqual(panel.x_var.get(), "125.00")
        self.assertAlmostEqual(pt.pt_to_mm(annot["x"]), 125.004, places=3)
        self.assertNotAlmostEqual(annot["x"], pt.mm_to_pt(125.00), places=4)

    def test_xy_survives_zoom_cycle(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        panel.x_var.set("100.00"); panel.y_var.set("60.00")
        panel._apply_xy()
        x0, y0 = annot["x"], annot["y"]

        for factor in (2.0, 0.25, 2.0):  # 100% -> 200% -> 50% -> 100%
            pw._zoom(factor)
            self.assertEqual(annot["x"], x0)
            self.assertEqual(annot["y"], y0)
            self.assertEqual(panel.x_var.get(), "100.00")
            self.assertEqual(panel.y_var.get(), "60.00")

    # ── 양방향 동기화 ────────────────────────────────────────
    def test_drag_updates_property_panel_xy(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages, click=(300, 300))
        panel = pw.prop_panel
        x_before = panel.x_var.get()

        pw._set_tool("select")
        pw._on_canvas_press(FakeEvent(x=300, y=300))
        self.assertIsNotNone(pw._move_state)
        pw._on_canvas_motion(FakeEvent(x=340, y=350))
        pw._on_canvas_release(FakeEvent(x=340, y=350))

        self.assertNotEqual(panel.x_var.get(), x_before)
        self.assertEqual(panel.x_var.get(), f"{pt.pt_to_mm(annot['x']):.2f}")
        self.assertEqual(panel.y_var.get(), f"{pt.pt_to_mm(annot['y']):.2f}")

    def test_panel_xy_edit_moves_canvas_text(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        panel.x_var.set("50.00"); panel.y_var.set("50.00")
        panel._apply_xy()
        expect_px, expect_py = pt.pdf_to_screen(
            annot["x"], annot["y"], pw._cur_pw, pw._cur_ph, pw._cur_rot,
            pw._sc, pw._cx, pw._cy)
        items = pw.canvas.find_withtag(f"annot_{annot['id']}")
        self.assertTrue(items)
        coords = pw.canvas.coords(items[0])
        self.assertAlmostEqual(coords[0], expect_px, places=2)
        self.assertAlmostEqual(coords[1], expect_py, places=2)

    # ── 내용 / 글꼴 / 크기 / 색상 / 굵게·기울임 / 정렬 / 회전 ──
    def test_content_edit_reflected_on_canvas(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        panel.text_var.set("검사완료 OK")
        panel._apply_text()
        self.assertEqual(annot["text"], "검사완료 OK")
        items = pw.canvas.find_withtag(f"annot_{annot['id']}")
        self.assertEqual(pw.canvas.itemcget(items[0], "text"), "검사완료 OK")

    def test_font_size_change_reflected(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        panel.size_var.set("30.00")
        panel._apply_size()
        self.assertEqual(annot["font_size"], 30.0)
        # 캔버스 폰트도 갱신되어 렌더링이 예외 없이 되는지 확인
        items = pw.canvas.find_withtag(f"annot_{annot['id']}")
        self.assertTrue(items)

    def test_font_size_invalid_input_rejected_without_crash(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        orig = annot["font_size"]
        with patch.object(pt.messagebox, "showwarning") as mock_warn:
            panel.size_var.set("hello")
            panel._apply_size()
            mock_warn.assert_called_once()
        self.assertEqual(annot["font_size"], orig)  # 값이 깨지지 않아야 함

        with patch.object(pt.messagebox, "showwarning") as mock_warn:
            panel.size_var.set("-5")
            panel._apply_size()
            mock_warn.assert_called_once()
        self.assertEqual(annot["font_size"], orig)

    def test_color_change_via_colorchooser(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        with patch("tkinter.colorchooser.askcolor", return_value=((0,0,0), "#00ff00")):
            panel._pick_color()
        self.assertEqual(annot["color"], "#00ff00")
        items = pw.canvas.find_withtag(f"annot_{annot['id']}")
        self.assertEqual(pw.canvas.itemcget(items[0], "fill"), "#00ff00")

    def test_bold_italic_toggle(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        self.assertFalse(annot.get("bold"))
        self.assertFalse(annot.get("italic"))
        panel.bold_var.set(True)
        panel.italic_var.set(True)
        panel._apply_style()
        self.assertTrue(annot["bold"])
        self.assertTrue(annot["italic"])

    def test_align_options(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        for label, expect in [("좌측","left"), ("가운데","center"), ("우측","right")]:
            panel.align_var.set(label)
            panel._apply_align()
            self.assertEqual(annot["align"], expect)

    def test_text_rotation_independent_of_page_rotation(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        panel.rot_var.set("90")
        panel._apply_rotation()
        self.assertEqual(annot["rotation"], 90.0)
        self.assertEqual(pages[0]["rot"], 0)   # 페이지 회전은 그대로

        pages[0]["rot"] = 180   # 페이지를 회전시켜도
        pw._show()
        self.assertEqual(annot["rotation"], 90.0)  # 텍스트 회전값은 그대로

    def test_rotation_invalid_input_rejected(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        with patch.object(pt.messagebox, "showwarning") as mock_warn:
            panel.rot_var.set("abc")
            panel._apply_rotation()
            mock_warn.assert_called_once()
        self.assertEqual(annot["rotation"], 0.0)

    def test_font_selection_applies(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        fonts = list(panel.font_combo["values"])
        self.assertTrue(fonts)
        other = next((f for f in fonts if f != annot.get("font")), fonts[0])
        panel.font_var.set(other)
        panel._apply_font()
        self.assertEqual(annot["font"], other)

    # ── 좌측 상단 기준 불변 (정렬 옵션이 X/Y 의 의미를 바꾸면 안 됨) ──
    def test_anchor_stays_top_left_regardless_of_align(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        x_before, y_before = annot["x"], annot["y"]
        panel = pw.prop_panel
        for label in ("좌측", "가운데", "우측"):
            panel.align_var.set(label)
            panel._apply_align()
            self.assertEqual(annot["x"], x_before)
            self.assertEqual(annot["y"], y_before)
            items = pw.canvas.find_withtag(f"annot_{annot['id']}")
            self.assertEqual(pw.canvas.itemcget(items[0], "anchor"), "nw")

    # ── 페이지 복제 시 새 필드도 독립적으로 복사되는지 ─────────
    def test_duplicate_page_copies_new_fields_independently(self):
        ot = pt.OrganizeTab(self.root)
        ot._load_pdfs([self.pdf_path])
        ot.pages[0]["annots"].append({
            "id": 500, "type": "text", "text": "hi", "x": 10, "y": 10,
            "font": pt.DEFAULT_ANNOT_FONT, "font_size": 12.0,
            "color": "#111111", "bold": False, "italic": False,
            "align": "left", "rotation": 0.0,
        })
        ot._hov_action("dup", 0)
        orig, dup = ot.pages[0], ot.pages[1]
        dup["annots"][0]["color"] = "#ffffff"
        dup["annots"][0]["bold"] = True
        self.assertEqual(orig["annots"][0]["color"], "#111111")
        self.assertFalse(orig["annots"][0]["bold"])

    # ── 선택 해제 시 패널 숨김 (17번 요구사항) ─────────────────
    def test_panel_hidden_when_nothing_selected(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        self.assertIn(pw.prop_panel, pw.prop_panel.master.pack_slaves())
        pw._select_annot(None)
        self.assertNotIn(pw.prop_panel, pw.prop_panel.master.pack_slaves())

    # ── 기존 기능(정리 탭/미리보기) 회귀 확인 ──────────────────
    def test_existing_features_unaffected(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        # 줌/팬
        pw._zoom(1.5); self.assertAlmostEqual(pw.zoom, 1.5)
        pw.pan_x = 10; pw.pan_y = 5; pw._show()
        # 페이지 회전 (기존 버튼)
        pw._rotate(90)
        self.assertEqual(pages[0]["rot"], 90)


# ══════════════════════════════════════════════════════════
#  5. Phase 4 추가 검증 — 회전 분리, 페이지 크기 일반화,
#     하위호환(레거시 annot), 단축키/포커스 충돌 방지
# ══════════════════════════════════════════════════════════
class TestPhase4ExtraVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = pt.TkinterDnD.Tk() if pt.DND_OK else pt.tk.Tk()
        cls.root.withdraw()
        cls.tmpdir = tempfile.mkdtemp(prefix="pdftool_test_")
        cls.pdf_path_a4 = os.path.join(cls.tmpdir, "a4.pdf")
        make_pdf(cls.pdf_path_a4, sizes=((595.28, 841.89),))
        cls.pdf_path_a3 = os.path.join(cls.tmpdir, "a3.pdf")
        make_pdf(cls.pdf_path_a3, sizes=((841.89, 1190.55),))  # A3

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _load(self, path):
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)   # pending after() 콜백이 소멸된 위젯을 참조하지 않도록
        ot._load_pdfs([path])
        return ot.pages

    def _open(self, pages, geom="1150x820+0+0"):
        pw = pt.PreviewWin(self.root, pages, 0)
        pw.update_idletasks()
        pw.geometry(geom)
        pw.update_idletasks()
        pw._show()
        self.addCleanup(pw.destroy)
        return pw

    # ── 1. X/Y 는 항상 텍스트 좌측 상단 기준 (정렬 무관) ───────
    def test_xy_anchor_unaffected_by_alignment(self):
        pages = self._load(self.pdf_path_a4)
        pw = self._open(pages)
        pw._toggle_edit(); pw._set_tool("text")
        with patch.object(pt.PreviewWin, "_ask_text", return_value="anchor-test"):
            pw._on_canvas_press(FakeEvent(x=300, y=300))
        annot = pages[0]["annots"][0]
        x0, y0 = annot["x"], annot["y"]
        panel = pw.prop_panel
        for label in ("좌측", "가운데", "우측"):
            panel.align_var.set(label); panel._apply_align()
            self.assertEqual(annot["x"], x0)
            self.assertEqual(annot["y"], y0)
            items = pw.canvas.find_withtag(f"annot_{annot['id']}")
            self.assertEqual(pw.canvas.itemcget(items[0], "anchor"), "nw")

    # ── 2/3. 페이지 회전 vs 텍스트 회전 완전 분리 + 0/90/180/270 실측 ──
    def test_page_and_text_rotation_are_fully_independent_all_angles(self):
        pages = self._load(self.pdf_path_a4)
        pw = self._open(pages)
        pw._toggle_edit(); pw._set_tool("text")
        with patch.object(pt.PreviewWin, "_ask_text", return_value="rot-test"):
            pw._on_canvas_press(FakeEvent(x=300, y=300))
        annot = pages[0]["annots"][0]
        panel = pw.prop_panel
        panel.x_var.set("80.00"); panel.y_var.set("40.00"); panel._apply_xy()
        x_pt, y_pt = annot["x"], annot["y"]

        for page_rot in (0, 90, 180, 270, 0):
            pages[0]["rot"] = page_rot
            pw._show()
            # 페이지 회전을 바꿔도 annot 의 x/y/rotation 은 절대 바뀌면 안 됨
            self.assertEqual(annot["x"], x_pt)
            self.assertEqual(annot["y"], y_pt)
            self.assertEqual(annot.get("rotation", 0.0), 0.0)

        # 이번엔 반대로: 텍스트 자체 rotation 을 바꿔도 페이지 rot 은 그대로
        pages[0]["rot"] = 90
        for text_rot in (0, 90, 180, 270, 45, 0):
            panel.rot_var.set(str(text_rot))
            panel._apply_rotation()
            self.assertEqual(annot["rotation"], float(text_rot % 360))
            self.assertEqual(pages[0]["rot"], 90)   # 페이지 회전은 불변
            self.assertEqual(annot["x"], x_pt)       # 위치도 불변
            self.assertEqual(annot["y"], y_pt)

    def test_rotation_direction_matches_page_convention_visually(self):
        """canvas.create_text 의 angle 파라미터가 실제로 우리 앱의
        '시계방향 +' 규약과 일치하는 방향으로 렌더링되는지, 실제 렌더 결과
        (아이템 bbox 이동 방향)로 확인한다 — 계산상의 추정이 아니라 실측."""
        pages = self._load(self.pdf_path_a4)
        pw = self._open(pages)
        pw._toggle_edit(); pw._set_tool("text")
        with patch.object(pt.PreviewWin, "_ask_text", return_value="AB"):
            pw._on_canvas_press(FakeEvent(x=400, y=400))
        annot = pages[0]["annots"][0]
        annot["font_size"] = 30.0

        panel = pw.prop_panel
        panel.rot_var.set("0"); panel._apply_rotation()
        pw._show()
        item = pw.canvas.find_withtag(f"annot_{annot['id']}")[0]
        bbox0 = pw.canvas.bbox(item)
        cy0 = (bbox0[1] + bbox0[3]) / 2
        anchor_x, anchor_y = pw.canvas.coords(item)

        panel.rot_var.set("90"); panel._apply_rotation()
        pw._show()
        item = pw.canvas.find_withtag(f"annot_{annot['id']}")[0]
        bbox90 = pw.canvas.bbox(item)
        cy90 = (bbox90[1] + bbox90[3]) / 2

        # anchor="nw" 이고 rotation=0 일 때 글자는 앵커점에서 오른쪽/아래로
        # 뻗어나간다. 우리 앱 규약(양수=시계방향)대로라면 90도 회전 시
        # "오른쪽으로 뻗던 텍스트"가 "아래로 뻗는" 모습이 되어야 한다
        # (오른쪽->아래 는 시계방향 90도가 맞다).
        self.assertGreater(cy90, anchor_y - 1,
            "90도 회전 시 텍스트가 앵커점 아래쪽으로 뻗어야 시계방향(앱 규약)과 일치함")

    # ── 4. X/Y 직접 입력 2회 연속 변경 ─────────────────────────
    def test_xy_direct_input_twice_moves_correctly(self):
        pages = self._load(self.pdf_path_a4)
        pw = self._open(pages)
        pw._toggle_edit(); pw._set_tool("text")
        with patch.object(pt.PreviewWin, "_ask_text", return_value="xy-test"):
            pw._on_canvas_press(FakeEvent(x=300, y=300))
        annot = pages[0]["annots"][0]
        panel = pw.prop_panel

        for x_mm, y_mm in [(50.00, 30.00), (100.00, 100.00)]:
            panel.x_var.set(f"{x_mm:.2f}"); panel.y_var.set(f"{y_mm:.2f}")
            panel._apply_xy()
            self.assertAlmostEqual(pt.pt_to_mm(annot["x"]), x_mm, places=6)
            self.assertAlmostEqual(pt.pt_to_mm(annot["y"]), y_mm, places=6)
            expect_px, expect_py = pt.pdf_to_screen(
                annot["x"], annot["y"], pw._cur_pw, pw._cur_ph, pw._cur_rot,
                pw._sc, pw._cx, pw._cy)
            item = pw.canvas.find_withtag(f"annot_{annot['id']}")[0]
            actual = pw.canvas.coords(item)
            self.assertAlmostEqual(actual[0], expect_px, places=2)
            self.assertAlmostEqual(actual[1], expect_py, places=2)

    # ── 5. 줌 50/100/200/400% 에서도 패널 mm 표시 불변 ─────────
    def test_zoom_50_100_200_400_panel_unchanged(self):
        pages = self._load(self.pdf_path_a4)
        pw = self._open(pages)
        pw._toggle_edit(); pw._set_tool("text")
        with patch.object(pt.PreviewWin, "_ask_text", return_value="zoom-test"):
            pw._on_canvas_press(FakeEvent(x=300, y=300))
        panel = pw.prop_panel
        panel.x_var.set("100.00"); panel.y_var.set("50.00"); panel._apply_xy()

        pw.zoom = 1.0; pw._show()
        for target_zoom in (0.5, 1.0, 2.0, 4.0):
            pw.zoom = target_zoom
            pw._show()
            self.assertEqual(panel.x_var.get(), "100.00")
            self.assertEqual(panel.y_var.get(), "50.00")

    # ── 7. 페이지 크기 하드코딩 금지 — A3 에서도 동일 로직 ─────
    def test_a3_page_uses_actual_dims_not_hardcoded(self):
        pages = self._load(self.pdf_path_a3)
        p = pages[0]
        self.assertAlmostEqual(pt.pt_to_mm(p["page_w_pt"]), 297.0, delta=0.1)
        self.assertAlmostEqual(pt.pt_to_mm(p["page_h_pt"]), 420.0, delta=0.1)

        pw = self._open(pages)
        pw._toggle_edit(); pw._set_tool("text")
        with patch.object(pt.PreviewWin, "_ask_text", return_value="a3-test"):
            pw._on_canvas_press(FakeEvent(x=300, y=300))
        annot = pages[0]["annots"][0]
        panel = pw.prop_panel
        # 패널에 표시되는 페이지 크기 안내 문구도 A3 실제 치수를 반영해야 함
        self.assertIn("297.00", panel.page_size_lbl.cget("text"))
        self.assertIn("420.00", panel.page_size_lbl.cget("text"))

        panel.x_var.set("200.00"); panel.y_var.set("300.00"); panel._apply_xy()
        expect_px, expect_py = pt.pdf_to_screen(
            annot["x"], annot["y"], pw._cur_pw, pw._cur_ph, pw._cur_rot,
            pw._sc, pw._cx, pw._cy)
        item = pw.canvas.find_withtag(f"annot_{annot['id']}")[0]
        actual = pw.canvas.coords(item)
        self.assertAlmostEqual(actual[0], expect_px, places=2)
        self.assertAlmostEqual(actual[1], expect_py, places=2)

    # ── 8. font_size 가 annotation 데이터에 정확히 저장되는지 ──
    def test_font_size_persisted_in_annotation_data(self):
        pages = self._load(self.pdf_path_a4)
        pw = self._open(pages)
        pw._toggle_edit(); pw._set_tool("text")
        with patch.object(pt.PreviewWin, "_ask_text", return_value="size-test"):
            pw._on_canvas_press(FakeEvent(x=300, y=300))
        annot = pages[0]["annots"][0]
        panel = pw.prop_panel
        panel.size_var.set("22.50")
        panel._apply_size()
        self.assertEqual(annot["font_size"], 22.5)
        # 패널을 닫았다 다시 선택해도(재로딩 시나리오) 값이 유지되는지
        pw._select_annot(None)
        pw._select_annot(annot["id"])
        self.assertEqual(panel.size_var.get(), "22.50")

    # ── 9. 레거시 annot(신규 필드 없음) 호환성 ─────────────────
    def test_legacy_annot_without_new_fields_works_without_error(self):
        pages = self._load(self.pdf_path_a4)
        # Phase 3 시절 형태 그대로 (font/size/color/bold/italic/align/rotation 없음)
        legacy = {"id": 12345, "type": "text", "text": "legacy", "x": 50.0, "y": 60.0}
        pages[0]["annots"].append(legacy)

        pw = self._open(pages)
        pw._show()  # 예외 없이 렌더링되어야 함
        items = pw.canvas.find_withtag(f"annot_{legacy['id']}")
        self.assertTrue(items)

        pw._toggle_edit()
        pw._select_annot(legacy["id"])   # 속성 패널에 기본값으로 채워져야 함
        panel = pw.prop_panel
        self.assertEqual(panel.font_var.get(), pt.DEFAULT_ANNOT_FONT)
        self.assertEqual(panel.size_var.get(), f"{pt.DEFAULT_ANNOT_SIZE:.2f}")
        self.assertEqual(panel.align_var.get(), "좌측")
        self.assertFalse(panel.bold_var.get())
        self.assertFalse(panel.italic_var.get())
        self.assertEqual(panel.rot_var.get(), "0.0")

        # 레거시 annot 을 그대로 다시 삭제/이동해도 에러 없어야 함
        panel.x_var.set("70.00"); panel._apply_xy()
        self.assertAlmostEqual(pt.pt_to_mm(legacy["x"]), 70.00, places=6)

    # ── 6(재확인). 드래그 이동 <-> 패널 양방향 동기화 재검증 ───
    def test_bidirectional_sync_drag_then_panel_edit(self):
        pages = self._load(self.pdf_path_a4)
        pw = self._open(pages)
        pw._toggle_edit(); pw._set_tool("text")
        with patch.object(pt.PreviewWin, "_ask_text", return_value="sync-test"):
            pw._on_canvas_press(FakeEvent(x=300, y=300))
        annot = pages[0]["annots"][0]
        panel = pw.prop_panel

        # 마우스 드래그 -> 패널 갱신
        pw._set_tool("select")
        pw._on_canvas_press(FakeEvent(x=300, y=300))
        pw._on_canvas_motion(FakeEvent(x=250, y=200))
        pw._on_canvas_release(FakeEvent(x=250, y=200))
        self.assertEqual(panel.x_var.get(), f"{pt.pt_to_mm(annot['x']):.2f}")
        self.assertEqual(panel.y_var.get(), f"{pt.pt_to_mm(annot['y']):.2f}")

        # 패널 입력 -> 캔버스 이동
        panel.x_var.set("60.00"); panel.y_var.set("60.00")
        panel._apply_xy()
        expect_px, expect_py = pt.pdf_to_screen(
            annot["x"], annot["y"], pw._cur_pw, pw._cur_ph, pw._cur_rot,
            pw._sc, pw._cx, pw._cy)
        item = pw.canvas.find_withtag(f"annot_{annot['id']}")[0]
        actual = pw.canvas.coords(item)
        self.assertAlmostEqual(actual[0], expect_px, places=2)
        self.assertAlmostEqual(actual[1], expect_py, places=2)

    # ── 10. 단축키 vs 속성패널 입력 충돌 방지 (실제 키 이벤트) ──
    def test_entry_keys_not_hijacked_by_previewwin_shortcuts(self):
        """
        참고: Xvfb 에는 창 관리자(WM)가 없고 PreviewWin 은 grab_set() 을 걸기
        때문에 focus_force() 로도 OS 레벨 포커스 이전이 항상 보장되진 않는다.
        그래서 "포커스가 실제로 옮겨졌는지"는 pw.focus_get() 을 모킹해서
        결정론적으로 재현하고, Entry 자체의 기본 동작(문자 입력/삭제/커서 이동/
        복사·붙여넣기)은 event_generate 로 위젯에 직접 이벤트를 보내 검증한다
        (event_generate 는 실제 OS 포커스와 무관하게 대상 위젯의 bindtag 를
        그대로 거치므로, Tk 기본 동작 자체를 확인하는 데는 문제가 없다).
        """
        # 클래스 공용 root 는 다른 테스트에서 창 깜빡임을 막으려고 withdraw()
        # 되어 있는데, 창관리자가 없는 Xvfb 에서는 root 가 withdraw 상태면 그
        # 자식 Toplevel(PreviewWin) 이 실제 X 키보드 포커스를 받지 못해
        # focus_force() 가 무력화된다 (실 Windows 환경과 무관한 테스트 환경
        # 제약). 이 테스트에서만 잠시 deiconify 했다가 끝나면 되돌린다.
        self.root.deiconify()
        self.addCleanup(self.root.withdraw)

        pages = self._load(self.pdf_path_a4)
        pw = self._open(pages)
        pw._toggle_edit(); pw._set_tool("text")
        with patch.object(pt.PreviewWin, "_ask_text", return_value="key-test"):
            pw._on_canvas_press(FakeEvent(x=300, y=300))
        panel = pw.prop_panel
        panel.x_var.set("100.00")
        entry = self._find_entry_for_var(panel, panel.x_var)
        # PreviewWin 은 모달 grab_set() 을 거는데, 이 테스트는 grab 자체가
        # 아니라 "Entry 입력이 단축키에 가로채이는지"를 확인하는 것이므로
        # grab 은 풀고 진행한다.
        pw.grab_release()
        entry.focus_force()
        pw.update()

        with patch.object(pw, "focus_get", return_value=entry):
            self.assertTrue(pw._focus_in_entry())

            zoom_before = pw.zoom
            idx_before = pw.idx
            selected_before = pw.selected_id

            entry.icursor(0)
            entry.event_generate("<KeyPress>", keysym="minus")   # '-' 입력
            pw.update()
            self.assertEqual(entry.get()[0], "-", "마이너스 입력이 축소 단축키에 가로채이면 안 됨")
            self.assertEqual(pw.zoom, zoom_before, "'-' 입력 중 페이지 줌이 바뀌면 안 됨")

            entry.icursor(pt.tk.END)
            entry.event_generate("<KeyPress>", keysym="period")
            pw.update()
            self.assertTrue(entry.get().endswith("."))

            before_del = entry.get()
            entry.icursor(1)
            entry.event_generate("<KeyPress>", keysym="Delete")
            pw.update()
            self.assertNotEqual(entry.get(), before_del)
            self.assertEqual(pw.selected_id, selected_before,
                "Entry 안에서 Delete 를 눌렀다고 선택된 텍스트 annot 이 삭제되면 안 됨")

            entry.event_generate("<KeyPress>", keysym="BackSpace")
            pw.update()  # 예외 없이 동작하면 충분

            entry.event_generate("<KeyPress>", keysym="Left")
            pw.update()
            self.assertEqual(pw.idx, idx_before, "Entry 안에서 Left 를 눌렀다고 페이지가 넘어가면 안 됨")

            entry.event_generate("<KeyPress>", keysym="Right")
            pw.update()
            self.assertEqual(pw.idx, idx_before, "Entry 안에서 Right 를 눌렀다고 페이지가 넘어가면 안 됨")

        # Ctrl+C / Ctrl+V — Tk 표준 복사/붙여넣기가 그대로 동작하는지.
        # 물리 키(<Control-c/v>) 대신 Tk 가상 이벤트(<<Copy>>/<<Paste>>)로
        # 확인한다 — 둘 다 동일한 표준 동작을 검증하지만, 가상 이벤트 쪽이
        # grab_release 직후처럼 포커스 상태가 애매한 상황에서도 안정적이다.
        # 위의 키 스트레스 테스트(마이너스/점/삭제/백스페이스)로 X 입력창
        # 내용이 숫자로 파싱 안 되는 상태일 수 있다. 이 상태에서 다른 입력창
        # (entry2)으로 포커스를 옮기면 <FocusOut> -> _apply_xy() 의 정상적인
        # 유효성 검사 경고창(messagebox.showwarning)이 뜨는 게 "맞는 동작"
        # 이지만, 사람이 없는 자동화 테스트에서는 그 모달이 응답을 못 받아
        # 무한 대기하므로 이 테스트에서는 경고창만 무해하게 눌러준다
        # (검증 로직 자체는 test_xy_input_mm_stored_as_pt_and_redisplayed 등
        # 다른 테스트에서 이미 확인함 — 여기서는 순수 키 입력 라우팅만 본다).
        with patch.object(pt.messagebox, "showwarning"):
            copied_text = entry.get()   # <FocusOut> 유효성검사로 나중에 값이
            entry.selection_range(0, pt.tk.END)   # 리셋될 수 있으니 복사 시점 값을 미리 저장
            pw.update()
            entry.event_generate("<<Copy>>")
            pw.update()
            entry2 = self._find_entry_for_var(panel, panel.y_var)
            entry2.focus_force()   # entry 의 <FocusOut>(_apply_xy 검증 실패 ->
            pw.update()            # refresh_xy_only) 부작용이 여기서 먼저 발생하므로
            entry2.delete(0, pt.tk.END)   # 그 이후에 비워야 paste 결과가 안 섞인다
            pw.update()
            entry2.event_generate("<<Paste>>")
            pw.update()
        self.assertEqual(entry2.get(), copied_text,
            "Ctrl+C/Ctrl+V 로 복사한 값이 다른 입력창에 그대로 붙여넣기 되어야 함")

    @staticmethod
    def _find_entry_for_var(panel, var):
        for child in panel.winfo_children():
            for w in ([child] + list(child.winfo_children())):
                if isinstance(w, pt.tk.Entry) and w.cget("textvariable") == str(var):
                    return w
        raise AssertionError("해당 변수에 연결된 Entry 를 찾지 못함")


if __name__ == "__main__":
    unittest.main()
