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


if __name__ == "__main__":
    unittest.main()
