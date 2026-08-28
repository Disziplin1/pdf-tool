"""
pdf_tool.py 자동 테스트 (unittest, 표준 라이브러리만 사용)

실행 방법 (Tkinter GUI 를 실제로 생성하므로 디스플레이가 필요):
    xvfb-run -a python -m unittest test_pdf_tool.py -v

테스트 대상:
  - 좌표 변환 함수 (mm/pt, 회전, 화면<->PDF) 는 순수 함수 테스트
  - OrganizeTab/PreviewWin 은 실제 Tk 위젯을 만들어 동작을 검증
  - 텍스트 생성은 팝업 대화상자 없이 클릭 즉시 기본 텍스트(DEFAULT_ANNOT_TEXT)로
    만들어지므로, 커스텀 내용이 필요한 테스트는 생성 후 annot["text"] 를 직접
    바꾸거나 prop_panel.text_var/_apply_text() 로 편집한다
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

    # ── 호버 버튼(🔍/↺/⧉/🗑) 위에서는 손가락 커서로 구분 ─────────
    def test_hover_shows_hand_cursor_over_action_buttons_and_move_cursor_over_card(self):
        ot = self._new_tab_with_pdf()
        ot.update_idletasks()
        ot._render()

        x0, y0 = ot._card_xy(0)
        # 카드 본체(버튼이 아닌 부분) 위에서는 이동 가능 커서
        ot._on_hover(FakeEvent(x=x0 + ot.CW // 2, y=y0 + 10))
        self.assertEqual(ot.canvas.cget("cursor"), "fleur")

        # 🔍(첫 번째 호버 버튼, rx=0.15) 위에서는 클릭 가능 손가락 커서
        bx = x0 + int(ot.CW * 0.15)
        by = y0 + ot.CH - ot.BBAR_H // 2
        ot._on_hover(FakeEvent(x=bx, y=by))
        self.assertEqual(ot.canvas.cget("cursor"), "hand2")

    # ── 카드 더블클릭 시 🔍 버튼과 동일하게 미리보기 열림 ──────
    def test_double_click_on_card_opens_preview(self):
        ot = self._new_tab_with_pdf()
        ot.update_idletasks()
        ot._render()
        x0, y0 = ot._card_xy(0)
        with patch.object(pt, "PreviewWin") as MockPreview:
            ot._on_double_click(FakeEvent(x=x0 + ot.CW // 2, y=y0 + 10))
        MockPreview.assert_called_once()
        self.assertEqual(MockPreview.call_args[0][2], 0)   # idx 인자

    def test_double_click_on_action_button_does_not_double_open(self):
        """🔍 버튼 위에서 더블클릭하면(=버튼을 두 번 누른 상황) 더블클릭
        핸들러가 또 한 번 미리보기를 열어 중복 실행되면 안 된다."""
        ot = self._new_tab_with_pdf()
        ot.update_idletasks()
        ot._render()
        x0, y0 = ot._card_xy(0)
        bx = x0 + int(ot.CW * 0.15)
        by = y0 + ot.CH - ot.BBAR_H // 2
        # 실제 사용 흐름처럼, 액션 바가 그려지도록 먼저 카드를 호버한다
        # (호버 액션 버튼은 _render() 가 아니라 _on_hover 가 그린다).
        ot._on_hover(FakeEvent(x=bx, y=by))
        with patch.object(pt, "PreviewWin") as MockPreview:
            ot._on_double_click(FakeEvent(x=bx, y=by))
        MockPreview.assert_not_called()

    # ── 미리보기에서 편집한 내용이 카드 썸네일에도 반영 ────────
    def test_preview_change_regenerates_thumbnail_with_annots(self):
        ot = self._new_tab_with_pdf()
        original_bytes = ot.pages[0]["pil"].tobytes()
        ot.pages[0]["annots"].append({
            "id": 9999, "type": "rect",
            "x0": pt.mm_to_pt(10), "y0": pt.mm_to_pt(10),
            "x1": pt.mm_to_pt(60), "y1": pt.mm_to_pt(60),
            "line_color": "#FF0000", "line_width": 3.0,
            "fill_color": "#FFFFFF", "fill_enabled": True,
        })
        ot._on_preview_change()
        self.assertNotEqual(ot.pages[0]["pil"].tobytes(), original_bytes,
            "annot 을 추가한 뒤 썸네일을 다시 만들었으면 픽셀이 달라져야 함")

    def test_open_preview_wires_on_change_to_thumbnail_refresh(self):
        ot = self._new_tab_with_pdf()
        with patch.object(pt, "PreviewWin") as MockPreview:
            ot._open_preview(0)
        kwargs = MockPreview.call_args[1]
        self.assertEqual(kwargs["on_change"], ot._on_preview_change)


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
        pw._on_canvas_press(FakeEvent(x=click_x, y=click_y))

        annots = pages[0]["annots"]
        self.assertEqual(len(annots), 1)
        a = annots[0]
        self.assertEqual(a["type"], "text")
        self.assertEqual(a["text"], pt.DEFAULT_ANNOT_TEXT)

        # 저장된 좌표가 PDF pt 공간이며, 클릭 지점을 screen_to_pdf 로 변환한 값과 일치해야 함
        expect_x, expect_y = pt.screen_to_pdf(
            click_x, click_y, pw._cur_pw, pw._cur_ph, pw._cur_rot, pw._sc, pw._cx, pw._cy)
        self.assertAlmostEqual(a["x"], expect_x, places=4)
        self.assertAlmostEqual(a["y"], expect_y, places=4)

    def test_created_text_is_drawn_on_canvas(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._toggle_edit(); pw._set_tool("text")
        pw._on_canvas_press(FakeEvent(x=250, y=250))
        aid = pages[0]["annots"][0]["id"]
        items = pw.canvas.find_withtag(f"annot_{aid}")
        self.assertTrue(len(items) >= 1)

    def test_click_creates_placeholder_text_without_modal_and_focuses_content(self):
        """팝업 대화상자 없이 클릭 즉시 기본 텍스트로 생성되고, 바로 타이핑해서
        바꿀 수 있도록 속성 패널의 '내용' 입력창에 포커스+전체선택 되어야 한다."""
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._toggle_edit(); pw._set_tool("text")
        pw._on_canvas_press(FakeEvent(x=250, y=250))
        self.assertEqual(len(pages[0]["annots"]), 1)
        annot = pages[0]["annots"][0]
        self.assertEqual(annot["text"], pt.DEFAULT_ANNOT_TEXT)
        self.assertEqual(pw.selected_id, annot["id"])

    def test_select_text(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._toggle_edit(); pw._set_tool("text")
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
        pw._on_canvas_press(FakeEvent(x=300, y=300))
        self.assertEqual(len(pages[0]["annots"]), 1)
        self.assertEqual(len(pages[1]["annots"]), 0)
        pages[0]["annots"][0]["text"] = "page0-text"

        pw._go(1)
        self.assertEqual(pw.idx, 1)
        self.assertIsNone(pw.selected_id)
        # 텍스트 하나를 만들고 나면 반복 생성을 막기 위해 선택 도구로 자동
        # 전환되므로, 다른 페이지에 두 번째 텍스트를 만들려면 다시 선택해야 함.
        pw._set_tool("text")
        pw._on_canvas_press(FakeEvent(x=200, y=200))
        self.assertEqual(len(pages[0]["annots"]), 1)
        self.assertEqual(len(pages[1]["annots"]), 1)
        pages[1]["annots"][0]["text"] = "page1-text"
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

        # Y 입력창은 좌하단 원점 기준으로 표시되므로, 내부 저장(좌상단 원점)
        # 값은 페이지 높이에서 뺀 값이어야 한다.
        page_h_mm = pt.pt_to_mm(panel.page_h_pt)
        self.assertAlmostEqual(annot["x"], pt.mm_to_pt(125.00), places=6)
        self.assertAlmostEqual(annot["y"], pt.mm_to_pt(page_h_mm - 35.00), places=6)
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
        page_h_mm = pt.pt_to_mm(panel.page_h_pt)
        self.assertEqual(panel.x_var.get(), f"{pt.pt_to_mm(annot['x']):.2f}")
        self.assertEqual(panel.y_var.get(), f"{page_h_mm - pt.pt_to_mm(annot['y']):.2f}")

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
        for key in ("left", "center", "right"):
            panel._set_align(key)
            self.assertEqual(annot["align"], key)

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

    def test_new_text_defaults_to_korean_capable_font(self):
        """새 텍스트의 기본 글꼴은 한글을 지원하는 폰트여야 한다
        (Arial 등을 기본값으로 쓰면 한글이 깨질 수 있음)."""
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        self.assertEqual(annot.get("font"), pt.DEFAULT_ANNOT_FONT)
        self.assertNotEqual(pt.DEFAULT_ANNOT_FONT.lower(), "arial")

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

    def test_align_icon_buttons_highlight_active_selection(self):
        """정렬 아이콘 버튼 중 현재 선택된 것만 강조색(ACCENT) 배경이 되고
        나머지는 TOOLBAR 배경으로 돌아가야 한다."""
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        for key in ("left", "center", "right"):
            panel._set_align(key)
            for other_key, btn in panel.align_btns.items():
                expect_bg = pt.ACCENT if other_key == key else pt.TOOLBAR
                self.assertEqual(str(btn.cget("bg")), expect_bg)

    def test_show_annot_reflects_existing_align_state(self):
        """기존에 정렬이 설정된 annot 을 선택하면 그에 맞는 아이콘 버튼이
        미리 강조 표시되어야 한다."""
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        annot["align"] = "center"
        pw._select_annot(None)
        pw._select_annot(annot["id"])
        self.assertEqual(str(panel.align_btns["center"].cget("bg")), pt.ACCENT)
        self.assertEqual(str(panel.align_btns["left"].cget("bg")), pt.TOOLBAR)
        self.assertEqual(str(panel.align_btns["right"].cget("bg")), pt.TOOLBAR)

    def test_font_size_stepper_increments_and_decrements(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        panel.size_var.set("20.00")
        panel._apply_size()
        panel._step_size(1)
        self.assertEqual(annot["font_size"], 21.0)
        self.assertEqual(panel.size_var.get(), "21.00")
        panel._step_size(-1)
        self.assertEqual(annot["font_size"], 20.0)
        self.assertEqual(panel.size_var.get(), "20.00")

    def test_font_size_stepper_clamps_at_minimum(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        panel.size_var.set("1.00")
        panel._apply_size()
        panel._step_size(-1)
        self.assertEqual(annot["font_size"], 1.0)
        self.assertEqual(panel.size_var.get(), "1.00")

    def test_font_size_direct_entry_still_works(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        panel.size_var.set("33.50")
        panel._apply_size()
        self.assertEqual(annot["font_size"], 33.5)

    # ── 정렬을 바꿔도 저장된 X/Y 좌표 자체는 그대로(기준선 역할) ──
    def test_xy_unchanged_but_anchor_follows_align(self):
        """정렬(좌/가운데/우측)은 annot 에 저장된 X 좌표를 바꾸지 않는다
        — 대신 그 X 를 기준선으로 삼아 텍스트가 어느 쪽을 그 선에 맞출지
        (anchor) 만 바뀐다."""
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        x_before, y_before = annot["x"], annot["y"]
        panel = pw.prop_panel
        expect_anchor = {"left": "nw", "center": "n", "right": "ne"}
        for key in ("left", "center", "right"):
            panel._set_align(key)
            self.assertEqual(annot["x"], x_before)
            self.assertEqual(annot["y"], y_before)
            items = pw.canvas.find_withtag(f"annot_{annot['id']}")
            self.assertEqual(pw.canvas.itemcget(items[0], "anchor"), expect_anchor[key])

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

    # ── 1. 정렬을 바꿔도 저장된 X/Y 좌표 자체는 그대로(기준선 역할) ──
    def test_xy_anchor_unaffected_by_alignment(self):
        """정렬은 저장된 X 좌표를 바꾸지 않는다 — 그 X 를 기준선 삼아
        텍스트가 좌/가운데/우측 중 어느 쪽을 맞출지(anchor)만 바뀐다."""
        pages = self._load(self.pdf_path_a4)
        pw = self._open(pages)
        pw._toggle_edit(); pw._set_tool("text")
        pw._on_canvas_press(FakeEvent(x=300, y=300))
        annot = pages[0]["annots"][0]
        x0, y0 = annot["x"], annot["y"]
        panel = pw.prop_panel
        expect_anchor = {"left": "nw", "center": "n", "right": "ne"}
        for key in ("left", "center", "right"):
            panel._set_align(key)
            self.assertEqual(annot["x"], x0)
            self.assertEqual(annot["y"], y0)
            items = pw.canvas.find_withtag(f"annot_{annot['id']}")
            self.assertEqual(pw.canvas.itemcget(items[0], "anchor"), expect_anchor[key])

    # ── 2/3. 페이지 회전 vs 텍스트 회전 완전 분리 + 0/90/180/270 실측 ──
    def test_page_and_text_rotation_are_fully_independent_all_angles(self):
        pages = self._load(self.pdf_path_a4)
        pw = self._open(pages)
        pw._toggle_edit(); pw._set_tool("text")
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
        pw._on_canvas_press(FakeEvent(x=300, y=300))
        annot = pages[0]["annots"][0]
        panel = pw.prop_panel

        page_h_mm = pt.pt_to_mm(panel.page_h_pt)
        for x_mm, y_mm in [(50.00, 30.00), (100.00, 100.00)]:
            panel.x_var.set(f"{x_mm:.2f}"); panel.y_var.set(f"{y_mm:.2f}")
            panel._apply_xy()
            self.assertAlmostEqual(pt.pt_to_mm(annot["x"]), x_mm, places=6)
            self.assertAlmostEqual(page_h_mm - pt.pt_to_mm(annot["y"]), y_mm, places=6)
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
        self.assertEqual(legacy.get("font", pt.DEFAULT_ANNOT_FONT), pt.DEFAULT_ANNOT_FONT)
        self.assertEqual(panel.size_var.get(), f"{pt.DEFAULT_ANNOT_SIZE:.2f}")
        self.assertEqual(panel.align_btns["left"].cget("bg"), pt.ACCENT)
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
        pw._on_canvas_press(FakeEvent(x=300, y=300))
        annot = pages[0]["annots"][0]
        panel = pw.prop_panel

        # 마우스 드래그 -> 패널 갱신
        pw._set_tool("select")
        pw._on_canvas_press(FakeEvent(x=300, y=300))
        pw._on_canvas_motion(FakeEvent(x=250, y=200))
        pw._on_canvas_release(FakeEvent(x=250, y=200))
        page_h_mm = pt.pt_to_mm(panel.page_h_pt)
        self.assertEqual(panel.x_var.get(), f"{pt.pt_to_mm(annot['x']):.2f}")
        self.assertEqual(panel.y_var.get(), f"{page_h_mm - pt.pt_to_mm(annot['y']):.2f}")

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


# ══════════════════════════════════════════════════════════
#  6. 편의성 개선 — 생성 흐름(팝업 제거), 드래그 깜빡임 제거,
#     X/Y 미세조정(방향키·휠)
# ══════════════════════════════════════════════════════════
class TestUsabilityImprovements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = pt.TkinterDnD.Tk() if pt.DND_OK else pt.tk.Tk()
        cls.root.withdraw()
        cls.tmpdir = tempfile.mkdtemp(prefix="pdftool_test_")
        cls.pdf_path = os.path.join(cls.tmpdir, "sample.pdf")
        make_pdf(cls.pdf_path, sizes=((595.28, 841.89),))

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _make_pages(self):
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([self.pdf_path])
        return ot.pages

    def _open_preview_with_text(self, pages, click=(300, 300)):
        pw = pt.PreviewWin(self.root, pages, 0)
        pw.update_idletasks(); pw.geometry("1150x820+0+0"); pw.update(); pw._show()
        self.addCleanup(pw.destroy)
        pw._toggle_edit(); pw._set_tool("text")
        pw._on_canvas_press(FakeEvent(x=click[0], y=click[1]))
        return pw, pages[0]["annots"][0]

    # ── 생성 흐름: 팝업 없이 즉시 생성 + 바로 타이핑 가능 ──────
    def test_create_text_has_no_modal_and_prefills_placeholder(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        self.assertEqual(annot["text"], pt.DEFAULT_ANNOT_TEXT)
        self.assertEqual(pw.selected_id, annot["id"])

    def test_create_text_selects_all_content_for_immediate_typing(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        entry = pw.prop_panel.content_entry
        self.assertEqual(entry.index("sel.first"), 0)
        self.assertEqual(entry.index("sel.last"), len(pt.DEFAULT_ANNOT_TEXT))

    # ── 드래그 중 전체 재렌더링(_show) 없이 annot만 다시 그림 ──
    def test_drag_does_not_trigger_full_page_rerender(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        pw._set_tool("select")
        x_before, y_before = annot["x"], annot["y"]

        show_calls = []
        orig_show = pt.PreviewWin._show
        def counting_show(self):
            show_calls.append(1)
            return orig_show(self)
        with patch.object(pt.PreviewWin, "_show", counting_show):
            photo_before = pw.photo
            pw._on_canvas_press(FakeEvent(x=300, y=300))
            for i in range(10):
                pw._on_canvas_motion(FakeEvent(x=300+i*4, y=300+i*3))
            pw._on_canvas_release(FakeEvent(x=340, y=330))

        self.assertEqual(show_calls, [],
            "드래그 중에는 페이지 배경을 다시 렌더링(_show)하면 안 됨 — 깜빡임의 원인")
        self.assertIs(pw.photo, photo_before,
            "드래그 후에도 배경 PhotoImage 객체가 재생성되지 않아야 함")
        # 재렌더링 없이도 실제 이동 자체는 정상적으로 반영되어야 함
        self.assertNotEqual((annot["x"], annot["y"]), (x_before, y_before))
        expect = pt.pdf_to_screen(annot["x"], annot["y"], pw._cur_pw, pw._cur_ph,
                                   pw._cur_rot, pw._sc, pw._cx, pw._cy)
        actual = pw.canvas.coords(pw.canvas.find_withtag(f"annot_{annot['id']}")[0])
        self.assertAlmostEqual(actual[0], expect[0], places=2)
        self.assertAlmostEqual(actual[1], expect[1], places=2)

    # ── 빈 캔버스를 드래그하는 팬(화면 이동)도 재렌더링 없이 동작해야 함 ──
    def test_panning_empty_canvas_does_not_trigger_full_page_rerender(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        pw._set_tool("select")
        pw._select_annot(None)   # 아무것도 선택 안 된 상태에서 빈 곳을 드래그

        show_calls = []
        orig_show = pt.PreviewWin._show
        def counting_show(self):
            show_calls.append(1)
            return orig_show(self)
        start_x, start_y = 50, 50
        end_x, end_y = 90, 80
        with patch.object(pt.PreviewWin, "_show", counting_show):
            photo_before = pw.photo
            cx_before, cy_before = pw._cx, pw._cy
            # annot 이 없는 빈 좌표를 클릭해서 팬을 시작
            pw._on_canvas_press(FakeEvent(x=start_x, y=start_y))
            for i in range(1, 11):
                pw._on_canvas_motion(FakeEvent(
                    x=start_x + (end_x-start_x)*i//10,
                    y=start_y + (end_y-start_y)*i//10))
            pw._on_canvas_release(FakeEvent(x=end_x, y=end_y))

        self.assertEqual(show_calls, [],
            "빈 캔버스를 드래그(팬)할 때도 페이지를 다시 렌더링하면 안 됨 — 깜빡임의 원인")
        self.assertIs(pw.photo, photo_before,
            "팬 중에도 배경 PhotoImage 객체가 재생성되지 않아야 함")
        # 팬 오프셋만큼 좌표 변환 기준점(_cx/_cy)도 함께 갱신되어야, 팬 이후의
        # 클릭이 화면에 실제로 보이는 위치와 어긋나지 않는다.
        self.assertAlmostEqual(pw._cx, cx_before + (end_x-start_x), places=2)
        self.assertAlmostEqual(pw._cy, cy_before + (end_y-start_y), places=2)

    def test_select_and_property_edit_do_not_trigger_full_page_rerender(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        show_calls = []
        orig_show = pt.PreviewWin._show
        def counting_show(self):
            show_calls.append(1)
            return orig_show(self)
        with patch.object(pt.PreviewWin, "_show", counting_show):
            pw._select_annot(None)
            pw._select_annot(annot["id"])
            panel.size_var.set("20.00"); panel._apply_size()
            panel.text_var.set("bar"); panel._apply_text()
        self.assertEqual(show_calls, [],
            "선택/속성 변경도 배경 재렌더링 없이 annot만 다시 그려야 함")

    # ── X/Y 미세조정: 방향키 / Shift+방향키 / 마우스 휠 ─────────
    def test_arrow_key_nudges_xy_by_point_one_mm(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        panel.x_var.set("100.00"); panel.y_var.set("50.00"); panel._apply_xy()

        panel._nudge_x(0.1)
        self.assertEqual(panel.x_var.get(), "100.10")
        self.assertAlmostEqual(pt.pt_to_mm(annot["x"]), 100.10, places=6)

        panel._nudge_x(-0.1)
        self.assertEqual(panel.x_var.get(), "100.00")

        panel._nudge_y(0.1)
        self.assertEqual(panel.y_var.get(), "50.10")

    def test_shift_arrow_nudges_xy_by_one_mm(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        panel.x_var.set("100.00"); panel.y_var.set("50.00"); panel._apply_xy()

        panel._nudge_x(1.0)
        self.assertEqual(panel.x_var.get(), "101.00")
        panel._nudge_y(1.0)
        self.assertEqual(panel.y_var.get(), "51.00")

    def test_mouse_wheel_nudges_xy(self):
        # 클래스 공용 root 는 다른 테스트의 창 깜빡임 방지를 위해 withdraw()
        # 되어 있는데, 창관리자가 없는 Xvfb 에서는 root 가 withdraw 상태면
        # 합성 MouseWheel(포인터 계열) 이벤트가 자식 Toplevel 까지 전달되지
        # 않는다 — KeyPress 계열과 달리 이 문제가 있어 이 테스트에서만
        # deiconify 했다가 되돌린다 (Windows 실사용 환경과는 무관).
        self.root.deiconify()
        self.addCleanup(self.root.withdraw)

        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        panel.x_var.set("100.00"); panel._apply_xy()
        # PreviewWin 의 모달 grab_set() 도 합성 MouseWheel 전달을 막으므로 해제.
        # (release 가 실제로 반영되려면 이벤트 루프를 한 번 돌려야 한다)
        pw.grab_release()
        pw.update()

        entry_x = self._find_entry_for_var_local(panel, panel.x_var)
        entry_x.event_generate("<MouseWheel>", delta=120)   # 휠 위로
        self.assertEqual(panel.x_var.get(), "100.10")
        entry_x.event_generate("<MouseWheel>", delta=-120)  # 휠 아래로
        self.assertEqual(panel.x_var.get(), "100.00")

    def test_nudge_applies_immediately_without_enter(self):
        """방향키/휠 조정은 Enter 없이 즉시 annot 과 Canvas 에 반영되어야 한다."""
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        panel.x_var.set("100.00"); panel.y_var.set("50.00"); panel._apply_xy()

        panel._nudge_x(0.1)  # Enter 를 누르지 않음
        self.assertAlmostEqual(pt.pt_to_mm(annot["x"]), 100.10, places=6)
        expect = pt.pdf_to_screen(annot["x"], annot["y"], pw._cur_pw, pw._cur_ph,
                                   pw._cur_rot, pw._sc, pw._cx, pw._cy)
        actual = pw.canvas.coords(pw.canvas.find_withtag(f"annot_{annot['id']}")[0])
        self.assertAlmostEqual(actual[0], expect[0], places=2)
        self.assertAlmostEqual(actual[1], expect[1], places=2)

    def test_nudge_invalid_state_does_not_crash(self):
        """숫자가 아닌 값이 들어있을 때 방향키를 눌러도 예외가 발생하면 안 됨."""
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        panel = pw.prop_panel
        panel.x_var.set("abc")
        try:
            panel._nudge_x(0.1)
        except Exception as e:
            self.fail(f"nudge 중 예외 발생: {e}")

    # ── 텍스트 기본 색상은 검정 ──────────────────────────────
    def test_default_text_color_is_black(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        self.assertEqual(annot["color"], "#000000")
        self.assertEqual(pw.prop_panel.color_btn.cget("bg"), "#000000")
        item = pw.canvas.find_withtag(f"annot_{annot['id']}")[0]
        self.assertEqual(pw.canvas.itemcget(item, "fill"), "#000000")

    # ── Esc 로 미리보기 창이 닫히면 안 됨(오직 ✕ 버튼으로만) ──
    def test_escape_does_not_close_preview_window(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        destroyed = []
        pw.bind("<Destroy>", lambda e: destroyed.append(1), add="+")
        pw.event_generate("<KeyPress>", keysym="Escape")
        pw.update()
        self.assertEqual(destroyed, [], "Esc 를 눌러도 미리보기 창이 닫히면 안 됨")
        self.assertTrue(pw.winfo_exists())

    # ── 전체화면 기본 시작 + 토글 버튼으로 창모드 전환 ─────────
    def test_preview_starts_fullscreen_and_toggle_switches_to_windowed(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        self.assertTrue(pw.is_fullscreen, "미리보기는 기본으로 전체화면 시작해야 함")
        self.assertEqual(pw.fullscreen_btn.cget("text"), "□")
        self.assertEqual(pw.fullscreen_btn.cget("fg"), pt.ACCENT)

        pw._toggle_fullscreen()
        self.assertFalse(pw.is_fullscreen)
        self.assertEqual(pw.fullscreen_btn.cget("text"), "□")
        self.assertEqual(pw.fullscreen_btn.cget("fg"), pt.TEXT_DIM)
        try:
            self.assertFalse(bool(pw.attributes("-fullscreen")))
        except pt.tk.TclError:
            pass  # 이 플랫폼에서 -fullscreen 속성 조회가 안 되면 상태 플래그만으로 충분

        pw._toggle_fullscreen()
        self.assertTrue(pw.is_fullscreen)
        self.assertEqual(pw.fullscreen_btn.cget("fg"), pt.ACCENT)

    # ── 텍스트 생성 후 자동으로 선택 도구로 전환 (반복 생성 방지) ─────
    def test_creating_text_auto_switches_tool_to_select(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        self.assertEqual(pw.tool, "select")
        self.assertEqual(pw.tool_btns["select"].cget("bg"), pt.ACCENT)
        self.assertEqual(pw.tool_btns["text"].cget("bg"), pt.TOOLBAR)

        # 도구가 자동으로 바뀌었으므로, 다른 빈 곳을 클릭해도 새 텍스트가 생기면 안 됨
        pw._on_canvas_press(FakeEvent(x=600, y=600))
        self.assertEqual(len(pages[0]["annots"]), 1)

    # ── 캔버스 클릭 시 속성패널 입력창에서 포커스를 되찾아 Delete 등
    #     단축키가 항상 캔버스 기준으로 동작하게 함 ─────────────────
    def test_selecting_annot_on_canvas_reclaims_keyboard_focus_from_entry(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        with patch.object(pw.canvas, "focus_set") as mock_focus_set:
            pw._on_canvas_press(FakeEvent(x=300, y=300))
        mock_focus_set.assert_called()

    # ── 텍스트가 선택된 상태면 방향키가 (입력창 포커스 여부와 무관하게)
    #     그 텍스트를 바로 이동시켜야 함 ──────────────────────────
    def test_arrow_keys_move_selected_text_even_without_entry_focus(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        x_before, y_before = annot["x"], annot["y"]

        with patch.object(pw, "focus_get", return_value=pw.canvas):
            self.assertFalse(pw._focus_in_entry())
            pw._on_key_right()
            pw._nudge_selected_y(0.1)

        self.assertNotEqual(annot["x"], x_before)
        self.assertNotEqual(annot["y"], y_before)

    def test_left_right_still_navigate_pages_when_nothing_selected(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        pw._select_annot(None)
        with patch.object(pw, "_go") as mock_go, \
             patch.object(pw, "focus_get", return_value=pw.canvas):
            pw._on_key_right()
        mock_go.assert_called_once_with(1)

    # ── 창 컨트롤(□/✕)이 네이티브 타이틀바처럼 서로 붙어있고,
    #     닫기 버튼에 마우스를 올리면 빨간색으로 강조되어야 함 ──────
    def test_window_control_buttons_touch_with_no_gap(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        self.assertIs(pw.fullscreen_btn.master, pw.close_btn.master)
        self.assertEqual(int(pw.fullscreen_btn.pack_info()["padx"]), 0)
        self.assertEqual(int(pw.close_btn.pack_info()["padx"]), 0)

    def test_close_button_hover_highlights_red(self):
        # 합성 <Enter>/<Leave>(포인터 계열) 이벤트는 Xvfb 에 창관리자가 없고
        # 클래스 공용 root 가 withdraw() 상태면 자식 Toplevel 까지 전달되지
        # 않는다 (test_mouse_wheel_nudges_xy 와 동일한 테스트 환경 제약이며
        # 실제 Windows 사용 환경과는 무관하다).
        self.root.deiconify()
        self.addCleanup(self.root.withdraw)

        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        pw.grab_release()
        pw.update()

        pw.close_btn.event_generate("<Enter>")
        pw.update()
        self.assertEqual(pw.close_btn.cget("bg"), "#E81123")
        self.assertEqual(pw.close_btn.cget("fg"), "white")
        pw.close_btn.event_generate("<Leave>")
        pw.update()
        self.assertEqual(pw.close_btn.cget("bg"), pt.BG)
        self.assertEqual(pw.close_btn.cget("fg"), pt.TEXT_DIM)

    # ── 속성 패널의 삭제 버튼 ─────────────────────────────────
    def test_delete_button_in_property_panel_removes_selected_text(self):
        pages = self._make_pages()
        pw, annot = self._open_preview_with_text(pages)
        self.assertEqual(len(pages[0]["annots"]), 1)
        pw.prop_panel._delete_annot()
        self.assertEqual(pages[0]["annots"], [])
        self.assertIsNone(pw.selected_id)

    @staticmethod
    def _find_entry_for_var_local(panel, var):
        for child in panel.winfo_children():
            for w in ([child] + list(child.winfo_children())):
                if isinstance(w, pt.tk.Entry) and w.cget("textvariable") == str(var):
                    return w
        raise AssertionError("해당 변수에 연결된 Entry 를 찾지 못함")


# ══════════════════════════════════════════════════════════
#  6. PDF 내보내기 — 텍스트 annot 이 실제로 결과 PDF 에 구워지는지
#     (편집기에만 보이고 저장된 파일에는 없던 버그의 회귀 테스트)
# ══════════════════════════════════════════════════════════
class TestExportBakesTextAnnots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = pt.TkinterDnD.Tk() if pt.DND_OK else pt.tk.Tk()
        cls.root.withdraw()
        cls.tmpdir = tempfile.mkdtemp(prefix="pdftool_export_test_")
        cls.pdf_path = os.path.join(cls.tmpdir, "sample.pdf")
        make_pdf(cls.pdf_path, sizes=((595.28, 841.89),))

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _make_pages(self):
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([self.pdf_path])
        return ot, ot.pages

    def _export(self, ot, out_path):
        with patch.object(pt.filedialog, "asksaveasfilename", return_value=out_path), \
             patch.object(pt.messagebox, "showinfo"), \
             patch.object(pt.messagebox, "showwarning"), \
             patch.object(pt.messagebox, "showerror") as mock_err:
            ot._export()
        self.assertFalse(mock_err.called,
            f"내보내기 중 오류: {mock_err.call_args}")

    def test_exported_pdf_contains_annot_text(self):
        ot, pages = self._make_pages()
        pages[0]["annots"].append({
            "id": 9001, "type": "text", "text": "안녕하세요",
            "x": pt.mm_to_pt(20), "y": pt.mm_to_pt(30),
            "font": pt.DEFAULT_ANNOT_FONT, "font_size": 20.0,
            "color": "#000000", "bold": False, "italic": False,
            "align": "left", "rotation": 0.0,
        })
        out = os.path.join(self.tmpdir, "out1.pdf")
        self._export(ot, out)

        self.assertTrue(os.path.exists(out))
        doc = fitz.open(out)
        text = doc[0].get_text()
        doc.close()
        self.assertIn("안녕하세요", text,
            "편집기에서 추가한 텍스트가 내보낸 PDF 안에 그대로 있어야 함")

    def test_exported_pdf_without_annots_still_works(self):
        """회귀 방지: annot 이 없는 일반적인 경우(텍스트를 하나도 안 만든 경우)도
        여전히 정상적으로 내보내져야 한다."""
        ot, pages = self._make_pages()
        out = os.path.join(self.tmpdir, "out_noannot.pdf")
        self._export(ot, out)
        self.assertTrue(os.path.exists(out))
        doc = fitz.open(out)
        self.assertEqual(len(doc), 1)
        doc.close()

    def test_exported_text_position_matches_editor_coords(self):
        """텍스트 위치(annot x/y, 좌상단 원점·Y아래증가)가 결과 PDF 에서도
        같은 지점에 나타나는지, 텍스트 블록의 bbox 로 확인한다."""
        ot, pages = self._make_pages()
        x_pt, y_pt = pt.mm_to_pt(15), pt.mm_to_pt(25)
        pages[0]["annots"].append({
            "id": 9002, "type": "text", "text": "POS",
            "x": x_pt, "y": y_pt,
            "font": pt.DEFAULT_ANNOT_FONT, "font_size": 24.0,
            "color": "#000000", "bold": False, "italic": False,
            "align": "left", "rotation": 0.0,
        })
        out = os.path.join(self.tmpdir, "out_pos.pdf")
        self._export(ot, out)

        doc = fitz.open(out)
        rects = doc[0].search_for("POS")
        doc.close()
        self.assertTrue(rects, "삽입한 텍스트를 결과 PDF 에서 찾지 못함")
        bbox = rects[0]
        # insert_text 는 베이스라인 기준이라 위쪽으로 약간의 오차(ascent 근처)가
        # 있을 수 있으므로 넉넉한 허용오차로 확인한다.
        self.assertAlmostEqual(bbox.x0, x_pt, delta=2.0)
        self.assertAlmostEqual(bbox.y0, y_pt, delta=6.0)

    def test_exported_text_alignment_shifts_relative_to_x(self):
        """정렬(좌/가운데/우측)은 X 좌표를 기준선으로 삼아 텍스트를
        움직여야 한다 — 한 줄짜리 텍스트에서도 실제로 효과가 있어야 함
        (여러 줄일 때 줄간 정렬에만 영향을 주던 이전 동작의 회귀 테스트)."""
        ot, pages = self._make_pages()
        x_pt, y_pt = pt.mm_to_pt(100), pt.mm_to_pt(50)
        results = {}
        for align in ("left", "center", "right"):
            pages[0]["annots"] = [{
                "id": 9010, "type": "text", "text": "ALIGN",
                "x": x_pt, "y": y_pt,
                "font": pt.DEFAULT_ANNOT_FONT, "font_size": 24.0,
                "color": "#000000", "bold": False, "italic": False,
                "align": align, "rotation": 0.0,
            }]
            out = os.path.join(self.tmpdir, f"out_align_{align}.pdf")
            self._export(ot, out)
            doc = fitz.open(out)
            rects = doc[0].search_for("ALIGN")
            doc.close()
            self.assertTrue(rects)
            results[align] = rects[0]

        # 좌측 정렬: 텍스트 왼쪽 끝이 X 좌표 근처
        self.assertAlmostEqual(results["left"].x0, x_pt, delta=2.0)
        # 우측 정렬: 텍스트 오른쪽 끝이 X 좌표 근처
        self.assertAlmostEqual(results["right"].x1, x_pt, delta=2.0)
        # 가운데 정렬: 텍스트 중심이 X 좌표 근처
        center_x = (results["center"].x0 + results["center"].x1) / 2
        self.assertAlmostEqual(center_x, x_pt, delta=2.0)
        # 세 정렬의 왼쪽 끝 위치는 서로 달라야 함(실제로 움직였다는 증거)
        self.assertNotAlmostEqual(results["left"].x0, results["center"].x0, delta=1.0)
        self.assertNotAlmostEqual(results["left"].x0, results["right"].x0, delta=1.0)

    def test_exported_text_color_is_applied(self):
        ot, pages = self._make_pages()
        pages[0]["annots"].append({
            "id": 9003, "type": "text", "text": "RED",
            "x": pt.mm_to_pt(20), "y": pt.mm_to_pt(20),
            "font": pt.DEFAULT_ANNOT_FONT, "font_size": 18.0,
            "color": "#FF0000", "bold": False, "italic": False,
            "align": "left", "rotation": 0.0,
        })
        out = os.path.join(self.tmpdir, "out_color.pdf")
        self._export(ot, out)

        doc = fitz.open(out)
        raw = doc[0].get_text("rawdict")
        doc.close()
        colors = {
            span["color"]
            for block in raw["blocks"] for line in block.get("lines", [])
            for span in line["spans"]
        }
        # sRGB 정수로 인코딩된 색상값에서 순수 빨강(0xFF0000)을 찾는다
        self.assertIn(0xFF0000, colors)

    def test_exported_multipage_annots_are_independent(self):
        """서로 다른 페이지의 annot 이 섞이지 않고 각자 페이지에만 나타나야 함."""
        make_pdf_multi = os.path.join(self.tmpdir, "multi.pdf")
        make_pdf(make_pdf_multi, sizes=((595.28, 841.89), (595.28, 841.89)))
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([make_pdf_multi])
        pages = ot.pages
        pages[0]["annots"].append({
            "id": 9101, "type": "text", "text": "PAGE-ONE",
            "x": pt.mm_to_pt(20), "y": pt.mm_to_pt(20),
            "font": pt.DEFAULT_ANNOT_FONT, "font_size": 16.0,
            "color": "#000000", "bold": False, "italic": False,
            "align": "left", "rotation": 0.0,
        })
        pages[1]["annots"].append({
            "id": 9102, "type": "text", "text": "PAGE-TWO",
            "x": pt.mm_to_pt(20), "y": pt.mm_to_pt(20),
            "font": pt.DEFAULT_ANNOT_FONT, "font_size": 16.0,
            "color": "#000000", "bold": False, "italic": False,
            "align": "left", "rotation": 0.0,
        })
        out = os.path.join(self.tmpdir, "out_multi.pdf")
        self._export(ot, out)

        doc = fitz.open(out)
        t0, t1 = doc[0].get_text(), doc[1].get_text()
        doc.close()
        self.assertIn("PAGE-ONE", t0)
        self.assertNotIn("PAGE-TWO", t0)
        self.assertIn("PAGE-TWO", t1)
        self.assertNotIn("PAGE-ONE", t1)

    def test_duplicated_page_annots_do_not_leak_into_original(self):
        """페이지를 복제한 뒤 복제본에만 텍스트를 추가해도, 같은 원본
        (src, pidx) 를 공유하는 원본 페이지의 결과물에는 그 텍스트가
        나타나면 안 된다 (소스 문서를 직접 수정하면 이게 깨질 수 있음)."""
        ot, pages = self._make_pages()
        ot._hov_action("dup", 0)
        self.assertEqual(len(ot.pages), 2)
        dup = ot.pages[1]
        dup["annots"].append({
            "id": 9201, "type": "text", "text": "ONLY-IN-DUP",
            "x": pt.mm_to_pt(20), "y": pt.mm_to_pt(20),
            "font": pt.DEFAULT_ANNOT_FONT, "font_size": 16.0,
            "color": "#000000", "bold": False, "italic": False,
            "align": "left", "rotation": 0.0,
        })
        out = os.path.join(self.tmpdir, "out_dup.pdf")
        self._export(ot, out)

        doc = fitz.open(out)
        t0, t1 = doc[0].get_text(), doc[1].get_text()
        doc.close()
        self.assertNotIn("ONLY-IN-DUP", t0)
        self.assertIn("ONLY-IN-DUP", t1)

    def test_export_applies_page_rotation_on_top_of_native(self):
        """pg["rot"] 만큼 페이지가 회전되어 저장되어야 한다 (원본 문서
        자체의 회전은 0 인 일반적인 경우)."""
        ot, pages = self._make_pages()
        pages[0]["rot"] = 90
        out = os.path.join(self.tmpdir, "out_rot.pdf")
        self._export(ot, out)

        doc = fitz.open(out)
        rotation = doc[0].rotation
        doc.close()
        self.assertEqual(rotation, 90)


# ══════════════════════════════════════════════════════════
#  7. 도형(사각형/화살표/강조) — 생성/선택/이동/삭제/렌더/내보내기
# ══════════════════════════════════════════════════════════
class TestShapeAnnots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = pt.TkinterDnD.Tk() if pt.DND_OK else pt.tk.Tk()
        cls.root.withdraw()
        cls.tmpdir = tempfile.mkdtemp(prefix="pdftool_shape_test_")
        cls.pdf_path = os.path.join(cls.tmpdir, "sample.pdf")
        make_pdf(cls.pdf_path, sizes=((595.28, 841.89),))

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _make_pages(self):
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([self.pdf_path])
        return ot.pages

    def _open_preview(self, pages):
        pw = pt.PreviewWin(self.root, pages, 0)
        pw.update_idletasks(); pw.geometry("1150x820+0+0"); pw.update(); pw._show()
        self.addCleanup(pw.destroy)
        pw._toggle_edit()
        return pw

    def _drag_create(self, pw, tool, p0, p1):
        pw._set_tool(tool)
        pw._on_canvas_press(FakeEvent(x=p0[0], y=p0[1]))
        pw._on_canvas_motion(FakeEvent(x=p1[0], y=p1[1]))
        pw._on_canvas_release(FakeEvent(x=p1[0], y=p1[1]))

    # ── 생성 ────────────────────────────────────────────────
    def test_drag_creates_rect_with_normalized_corners(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (400, 400), (300, 300))  # 왼쪽 위로 드래그
        self.assertEqual(len(pages[0]["annots"]), 1)
        a = pages[0]["annots"][0]
        self.assertEqual(a["type"], "rect")
        self.assertLess(a["x0"], a["x1"])
        self.assertLess(a["y0"], a["y1"])
        self.assertEqual(pw.selected_id, a["id"])

    def test_drag_creates_arrow_preserving_direction(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "arrow", (300, 300), (400, 250))
        a = pages[0]["annots"][0]
        self.assertEqual(a["type"], "arrow")
        # 화살표는 방향이 의미 있으므로 시작/끝을 정규화하면 안 됨
        expect_start = pt.screen_to_pdf(300, 300, pw._cur_pw, pw._cur_ph, pw._cur_rot,
                                         pw._sc, pw._cx, pw._cy)
        self.assertAlmostEqual(a["x0"], expect_start[0], places=4)
        self.assertAlmostEqual(a["y0"], expect_start[1], places=4)

    def test_drag_creates_highlight(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "highlight", (300, 300), (450, 330))
        a = pages[0]["annots"][0]
        self.assertEqual(a["type"], "highlight")
        self.assertEqual(a.get("fill_color"), pt.DEFAULT_HIGHLIGHT_COLOR)

    def test_tiny_drag_does_not_create_shape(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (300, 300), (301, 301))
        self.assertEqual(len(pages[0]["annots"]), 0)

    def test_creating_shape_auto_switches_tool_to_select(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (300, 300), (400, 380))
        self.assertEqual(pw.tool, "select")

    # ── 선택 시 도형 속성 패널 표시 ──────────────────────────
    def test_selecting_shape_shows_shape_panel_not_text_panel(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (300, 300), (400, 380))
        self.assertIn(pw.shape_panel, pw.shape_panel.master.pack_slaves())
        self.assertNotIn(pw.prop_panel, pw.prop_panel.master.pack_slaves())
        self.assertIs(pw.shape_panel.annot, pages[0]["annots"][0])

    def test_deselecting_hides_shape_panel(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (300, 300), (400, 380))
        pw._select_annot(None)
        self.assertNotIn(pw.shape_panel, pw.shape_panel.master.pack_slaves())

    # ── 이동 ────────────────────────────────────────────────
    def test_dragging_selected_rect_moves_both_corners_together(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (300, 300), (400, 380))
        a = pages[0]["annots"][0]
        w0, h0 = a["x1"] - a["x0"], a["y1"] - a["y0"]

        pw._set_tool("select")
        pw._on_canvas_press(FakeEvent(x=350, y=340))   # 사각형 내부 클릭
        self.assertIsNotNone(pw._move_state)
        pw._on_canvas_motion(FakeEvent(x=390, y=380))
        pw._on_canvas_release(FakeEvent(x=390, y=380))

        w1, h1 = a["x1"] - a["x0"], a["y1"] - a["y0"]
        self.assertAlmostEqual(w0, w1, places=4)
        self.assertAlmostEqual(h0, h1, places=4)

    # ── 삭제 ────────────────────────────────────────────────
    def test_delete_selected_shape_via_panel_button(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (300, 300), (400, 380))
        pw.shape_panel._delete_shape()
        self.assertEqual(pages[0]["annots"], [])
        self.assertIsNone(pw.selected_id)

    def test_delete_key_removes_selected_shape(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "arrow", (300, 300), (400, 380))
        pw._delete_selected_annot()
        self.assertEqual(pages[0]["annots"], [])

    # ── 속성 패널 편집 ──────────────────────────────────────
    def test_shape_panel_geom_edit_moves_shape(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (300, 300), (400, 380))
        panel = pw.shape_panel
        page_h_mm = pt.pt_to_mm(panel.page_h_pt)
        panel.x0_var.set("20.00"); panel.x1_var.set("60.00")
        panel.y0_var.set("30.00"); panel.y1_var.set("50.00")
        panel._apply_geom()
        a = pages[0]["annots"][0]
        self.assertAlmostEqual(pt.pt_to_mm(a["x0"]), 20.00, places=4)
        self.assertAlmostEqual(pt.pt_to_mm(a["x1"]), 60.00, places=4)
        # Y 는 좌하단 원점 기준 표시이므로 내부 저장은 페이지 높이 기준 반전값
        self.assertAlmostEqual(page_h_mm - pt.pt_to_mm(a["y0"]), 30.00, places=4)
        self.assertAlmostEqual(page_h_mm - pt.pt_to_mm(a["y1"]), 50.00, places=4)

    def test_shape_panel_line_width_and_color_apply(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (300, 300), (400, 380))
        panel = pw.shape_panel
        panel.line_width_var.set("5.0")
        panel._apply_line_width()
        a = pages[0]["annots"][0]
        self.assertEqual(a["line_width"], 5.0)

        panel.annot["line_color"] = "#00FF00"  # 색상선택 다이얼로그 없이 직접 확인
        self.assertEqual(a["line_color"], "#00FF00")

    def test_shape_panel_fill_toggle_applies(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (300, 300), (400, 380))
        panel = pw.shape_panel
        self.assertFalse(pages[0]["annots"][0].get("fill_enabled"))
        panel.fill_enabled_var.set(True)
        panel._apply_fill_enabled()
        self.assertTrue(pages[0]["annots"][0]["fill_enabled"])

    def test_arrow_panel_hides_fill_section(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "arrow", (300, 300), (400, 380))
        panel = pw.shape_panel
        self.assertNotIn(panel.fill_frame, panel.pack_slaves())
        self.assertIn(panel.line_frame, panel.pack_slaves())

    def test_highlight_panel_shows_only_highlight_color(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "highlight", (300, 300), (400, 380))
        panel = pw.shape_panel
        self.assertNotIn(panel.line_frame, panel.pack_slaves())
        self.assertNotIn(panel.fill_frame, panel.pack_slaves())
        self.assertIn(panel.highlight_frame, panel.pack_slaves())

    # ── 렌더링이 예외 없이 동작하는지 (회귀 방지) ──────────────
    def test_all_shape_types_render_without_crash(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (250, 250), (350, 320))
        pw._set_tool("rect")
        self._drag_create(pw, "arrow", (250, 400), (400, 450))
        self._drag_create(pw, "highlight", (250, 500), (400, 530))
        self.assertEqual(len(pages[0]["annots"]), 3)
        pw._redraw_annots()   # 예외 없이 완료되면 성공

    # ── PDF 내보내기 ────────────────────────────────────────
    def _export(self, ot, out_path):
        with patch.object(pt.filedialog, "asksaveasfilename", return_value=out_path), \
             patch.object(pt.messagebox, "showinfo"), \
             patch.object(pt.messagebox, "showwarning"), \
             patch.object(pt.messagebox, "showerror") as mock_err:
            ot._export()
        self.assertFalse(mock_err.called, f"내보내기 중 오류: {mock_err.call_args}")

    def test_export_bakes_rect_with_border_and_optional_fill(self):
        ot, pages = pt.OrganizeTab(self.root), None
        self.addCleanup(ot.destroy)
        ot._load_pdfs([self.pdf_path])
        pages = ot.pages
        pages[0]["annots"].append({
            "id": 501, "type": "rect",
            "x0": pt.mm_to_pt(20), "y0": pt.mm_to_pt(20),
            "x1": pt.mm_to_pt(60), "y1": pt.mm_to_pt(50),
            "line_color": "#FF0000", "line_width": 3.0,
            "fill_color": "#00FF00", "fill_enabled": True,
        })
        out = os.path.join(self.tmpdir, "out_rect.pdf")
        self._export(ot, out)

        doc = fitz.open(out)
        drawings = doc[0].get_drawings()
        doc.close()
        self.assertTrue(drawings, "사각형이 결과 PDF 에 그려진 벡터 도형으로 존재해야 함")

    def test_export_bakes_arrow_as_line_drawing(self):
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([self.pdf_path])
        pages = ot.pages
        pages[0]["annots"].append({
            "id": 502, "type": "arrow",
            "x0": pt.mm_to_pt(20), "y0": pt.mm_to_pt(20),
            "x1": pt.mm_to_pt(80), "y1": pt.mm_to_pt(60),
            "line_color": "#000000", "line_width": 2.0,
        })
        out = os.path.join(self.tmpdir, "out_arrow.pdf")
        self._export(ot, out)

        doc = fitz.open(out)
        drawings = doc[0].get_drawings()
        doc.close()
        self.assertGreaterEqual(len(drawings), 2, "화살표 선 + 화살촉이 그려져야 함")

    def test_export_bakes_highlight_as_native_highlight_annot(self):
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([self.pdf_path])
        pages = ot.pages
        pages[0]["annots"].append({
            "id": 503, "type": "highlight",
            "x0": pt.mm_to_pt(20), "y0": pt.mm_to_pt(20),
            "x1": pt.mm_to_pt(80), "y1": pt.mm_to_pt(30),
            "fill_color": "#FFFF00",
        })
        out = os.path.join(self.tmpdir, "out_highlight.pdf")
        self._export(ot, out)

        doc = fitz.open(out)
        page = doc[0]
        annots = list(page.annots())
        self.assertEqual(len(annots), 1)
        self.assertEqual(annots[0].type[1], "Highlight")
        doc.close()

    def test_export_shape_position_respects_native_source_rotation(self):
        """소스 PDF 자체가 이미 회전(native rotation)되어 있는 경우에도
        사각형이 화면에서 보던 자리 그대로 나와야 한다."""
        rotated_pdf = os.path.join(self.tmpdir, "rotated_native.pdf")
        doc = fitz.open()
        page = doc.new_page(width=595.28, height=841.89)
        page.set_rotation(90)
        doc.save(rotated_pdf)
        doc.close()

        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([rotated_pdf])
        pages = ot.pages
        # page_w_pt/page_h_pt 는 이미 회전 반영된(swap 된) 값이어야 함
        self.assertAlmostEqual(pages[0]["page_w_pt"], 841.89, places=1)
        self.assertAlmostEqual(pages[0]["page_h_pt"], 595.28, places=1)

        pages[0]["annots"].append({
            "id": 504, "type": "rect",
            "x0": pt.mm_to_pt(10), "y0": pt.mm_to_pt(10),
            "x1": pt.mm_to_pt(30), "y1": pt.mm_to_pt(25),
            "line_color": "#000000", "line_width": 2.0,
            "fill_color": "#FFFFFF", "fill_enabled": False,
        })
        out = os.path.join(self.tmpdir, "out_native_rot.pdf")
        self._export(ot, out)

        doc = fitz.open(out)
        drawings = doc[0].get_drawings()
        self.assertTrue(drawings)
        doc.close()

    # ── 사각형 기본 선 색상 ─────────────────────────────────
    def test_new_rect_defaults_to_white_border(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (300, 300), (400, 380))
        a = pages[0]["annots"][0]
        self.assertEqual(a["line_color"], pt.DEFAULT_RECT_LINE_COLOR)
        self.assertEqual(a["line_color"], "#FFFFFF")

    # ── 핸들로 크기/끝점 조정 ───────────────────────────────
    def test_rect_corner_handle_resizes_only_that_corner(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (300, 300), (500, 450))
        a = pages[0]["annots"][0]
        x0_before, y0_before = a["x0"], a["y0"]

        sx, sy = pt.pdf_to_screen(a["x1"], a["y1"], pw._cur_pw, pw._cur_ph,
                                   pw._cur_rot, pw._sc, pw._cx, pw._cy)
        handle = pw._handle_hit_test(sx, sy)
        self.assertIsNotNone(handle)
        self.assertEqual(handle["handle"], "x1y1")

        pw._on_canvas_press(FakeEvent(x=int(sx), y=int(sy)))
        self.assertIsNotNone(pw._resize_state)
        pw._on_canvas_motion(FakeEvent(x=int(sx)+40, y=int(sy)+20))
        pw._on_canvas_release(FakeEvent(x=int(sx)+40, y=int(sy)+20))

        # 반대쪽(x0,y0) 코너는 그대로여야 함
        self.assertAlmostEqual(a["x0"], x0_before, places=2)
        self.assertAlmostEqual(a["y0"], y0_before, places=2)
        self.assertGreater(a["x1"], x0_before)
        self.assertGreater(a["y1"], y0_before)
        self.assertIsNone(pw._resize_state)

    def test_rect_handle_crossing_opposite_corner_keeps_normalized(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (400, 400), (600, 550))
        a = pages[0]["annots"][0]

        sx, sy = pt.pdf_to_screen(a["x0"], a["y0"], pw._cur_pw, pw._cur_ph,
                                   pw._cur_rot, pw._sc, pw._cx, pw._cy)
        pw._on_canvas_press(FakeEvent(x=int(sx), y=int(sy)))
        pw._on_canvas_motion(FakeEvent(x=700, y=650))  # 반대쪽 코너를 넘어서 드래그
        self.assertLess(a["x0"], a["x1"])
        self.assertLess(a["y0"], a["y1"])
        pw._on_canvas_release(FakeEvent(x=700, y=650))

    def test_arrow_endpoint_handle_moves_only_that_end(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "arrow", (300, 300), (500, 400))
        a = pages[0]["annots"][0]
        x0_before, y0_before = a["x0"], a["y0"]

        sx1, sy1 = pt.pdf_to_screen(a["x1"], a["y1"], pw._cur_pw, pw._cur_ph,
                                     pw._cur_rot, pw._sc, pw._cx, pw._cy)
        handle = pw._handle_hit_test(sx1, sy1)
        self.assertEqual(handle["handle"], "p1")

        pw._on_canvas_press(FakeEvent(x=int(sx1), y=int(sy1)))
        pw._on_canvas_motion(FakeEvent(x=int(sx1)+60, y=int(sy1)-30))
        pw._on_canvas_release(FakeEvent(x=int(sx1)+60, y=int(sy1)-30))

        self.assertAlmostEqual(a["x0"], x0_before, places=2)
        self.assertAlmostEqual(a["y0"], y0_before, places=2)
        self.assertNotAlmostEqual(a["x1"], x0_before + (500-300), places=1)

    def test_handles_only_appear_for_selected_shape(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (300, 300), (400, 380))
        a = pages[0]["annots"][0]
        sx, sy = pt.pdf_to_screen(a["x1"], a["y1"], pw._cur_pw, pw._cur_ph,
                                   pw._cur_rot, pw._sc, pw._cx, pw._cy)
        self.assertIsNotNone(pw._handle_hit_test(sx, sy))
        pw._select_annot(None)
        self.assertIsNone(pw._handle_hit_test(sx, sy))


# ══════════════════════════════════════════════════════════
#  8. 이미지 직접 불러오기(정리 탭) + jpg/png 로 내보내기
# ══════════════════════════════════════════════════════════
class TestImageImportAndExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = pt.TkinterDnD.Tk() if pt.DND_OK else pt.tk.Tk()
        cls.root.withdraw()
        cls.tmpdir = tempfile.mkdtemp(prefix="pdftool_img_test_")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _make_image(self, name, size=(900, 600), color=(200, 50, 50)):
        from PIL import Image as PILImage
        path = os.path.join(self.tmpdir, name)
        PILImage.new("RGB", size, color).save(path)
        return path

    def _export(self, ot, out_path):
        with patch.object(pt.filedialog, "asksaveasfilename", return_value=out_path), \
             patch.object(pt.messagebox, "showinfo"), \
             patch.object(pt.messagebox, "showwarning"), \
             patch.object(pt.messagebox, "showerror") as mock_err:
            ot._export()
        self.assertFalse(mock_err.called, f"내보내기 중 오류: {mock_err.call_args}")

    # ── 이미지를 정리 탭에 직접 불러오기 ────────────────────
    def test_loading_jpg_creates_a_single_editable_page(self):
        img = self._make_image("photo.jpg")
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([img])
        self.assertEqual(len(ot.pages), 1)
        pg = ot.pages[0]
        self.assertTrue(pg["src"].lower().endswith(".pdf"),
            "내부적으로는 임시 PDF로 변환되어 나머지 파이프라인과 동일하게 다뤄져야 함")
        self.assertEqual(pg["annots"], [])

    def test_loaded_image_page_size_is_reasonable_not_1px_1pt(self):
        """72dpi(1px=1pt) 그대로 열면 900px 폭 사진이 900pt(약 317mm)가
        되어버리는데, 150dpi 기준으로 잡으면 훨씬 상식적인 크기가 된다."""
        img = self._make_image("wide.png", size=(1500, 1000))
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([img])
        pg = ot.pages[0]
        # 150dpi 기준: 1500px / 150 * 72 = 720pt (약 254mm)
        self.assertAlmostEqual(pg["page_w_pt"], 720.0, delta=1.0)
        self.assertAlmostEqual(pg["page_h_pt"], 480.0, delta=1.0)

    def test_image_page_can_have_text_and_shapes_added(self):
        img = self._make_image("doc.png")
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([img])
        pages = ot.pages
        pw = pt.PreviewWin(self.root, pages, 0)
        self.addCleanup(pw.destroy)
        pw.update_idletasks(); pw.geometry("1150x820+0+0"); pw.update(); pw._show()
        self.assertIsNotNone(pw._sc, "이미지에서 변환된 페이지도 정상 렌더링되어야 함")
        pw._toggle_edit(); pw._set_tool("text")
        pw._on_canvas_press(FakeEvent(x=300, y=300))
        self.assertEqual(len(pages[0]["annots"]), 1)

    def test_multiple_images_load_as_independent_pages(self):
        img1 = self._make_image("a.jpg", color=(200,0,0))
        img2 = self._make_image("b.jpg", color=(0,200,0))
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([img1, img2])
        self.assertEqual(len(ot.pages), 2)
        self.assertNotEqual(ot.pages[0]["src"], ot.pages[1]["src"])

    # ── PDF/이미지 혼합 로딩도 정상 동작 ────────────────────
    def test_pdf_and_image_can_be_mixed_in_same_project(self):
        pdf_path = os.path.join(self.tmpdir, "doc.pdf")
        make_pdf(pdf_path, sizes=((595.28, 841.89),))
        img = self._make_image("photo.jpg")
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([pdf_path, img])
        self.assertEqual(len(ot.pages), 2)

    # ── jpg/png 로 내보내기 ─────────────────────────────────
    def test_export_single_image_page_as_png(self):
        img = self._make_image("single.png")
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([img])
        out = os.path.join(self.tmpdir, "result.png")
        self._export(ot, out)

        self.assertTrue(os.path.exists(out))
        from PIL import Image as PILImage
        with PILImage.open(out) as saved:
            self.assertEqual(saved.format, "PNG")

    def test_export_single_page_as_jpg(self):
        img = self._make_image("single2.png")
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([img])
        out = os.path.join(self.tmpdir, "result.jpg")
        self._export(ot, out)

        self.assertTrue(os.path.exists(out))
        from PIL import Image as PILImage
        with PILImage.open(out) as saved:
            self.assertEqual(saved.format, "JPEG")

    def test_export_multipage_as_png_creates_one_file_per_page(self):
        pdf_path = os.path.join(self.tmpdir, "multi.pdf")
        make_pdf(pdf_path, sizes=((595.28, 841.89), (595.28, 841.89), (595.28, 841.89)))
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([pdf_path])
        self.assertEqual(len(ot.pages), 3)

        out = os.path.join(self.tmpdir, "multi_out.png")
        self._export(ot, out)

        expected = [
            os.path.join(self.tmpdir, "multi_out_p001.png"),
            os.path.join(self.tmpdir, "multi_out_p002.png"),
            os.path.join(self.tmpdir, "multi_out_p003.png"),
        ]
        for p in expected:
            self.assertTrue(os.path.exists(p), f"{p} 가 생성되어야 함")
        # 페이지 수만큼 원래 지정한 파일명 자체는 생성되지 않아야 함(각 페이지 파일로 대체)
        self.assertFalse(os.path.exists(out))

    def test_exported_image_reflects_added_text(self):
        """이미지를 불러와 텍스트를 추가한 뒤 jpg로 저장하면, 저장된
        이미지 안에 그 텍스트가 실제로 그려져 있어야 한다 — 픽셀 검사
        대신 같은 굽기 결과물을 pdf로도 저장해 텍스트 추출로 확인."""
        img = self._make_image("withtext.png", size=(800, 600))
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([img])
        pages = ot.pages
        pages[0]["annots"].append({
            "id": 7001, "type": "text", "text": "이미지 위 텍스트",
            "x": pt.mm_to_pt(10), "y": pt.mm_to_pt(10),
            "font": pt.DEFAULT_ANNOT_FONT, "font_size": 24.0,
            "color": "#000000", "bold": False, "italic": False,
            "align": "left", "rotation": 0.0,
        })
        doc = ot._build_baked_doc()
        text = doc[0].get_text()
        doc.close()
        self.assertIn("이미지 위 텍스트", text)

    # ── EXIF Orientation 보정 ────────────────────────────────
    def test_exif_rotated_photo_loads_upright(self):
        """휴대폰 사진처럼 실제 픽셀은 가로(landscape)인데 EXIF
        Orientation 태그로 세로로 보이게 지정된 경우, 그 태그를 무시하고
        가로 그대로 불러오면 사진이 옆으로 눕는다 — 태그를 반영해 세로
        페이지로 들어와야 한다."""
        from PIL import Image as PILImage
        path = os.path.join(self.tmpdir, "exif_landscape.jpg")
        img = PILImage.new("RGB", (800, 400), (255, 255, 255))
        exif = img.getexif()
        exif[0x0112] = 6   # Orientation 6: 90도 시계방향으로 회전해야 올바름
        img.save(path, exif=exif)

        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([path])
        pg = ot.pages[0]
        # EXIF 보정을 반영하면 800x400(가로) 원본 픽셀이 400x800(세로)로
        # 바뀌어야 하므로, 페이지도 너비<높이(세로)가 되어야 한다.
        self.assertLess(pg["page_w_pt"], pg["page_h_pt"])

    def test_photo_without_exif_is_unaffected(self):
        """EXIF 태그가 없는 일반 이미지는 그대로(가로는 가로로) 들어와야
        한다 — 보정 로직이 방향 정보가 없을 때 엉뚱하게 돌리면 안 됨."""
        img = self._make_image("plain_landscape.png", size=(800, 400))
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([img])
        pg = ot.pages[0]
        self.assertGreater(pg["page_w_pt"], pg["page_h_pt"])

    # ── 내보내기 기본 형식이 불러온 사진 형식을 따라가는지 ─────
    def test_export_dialog_defaults_to_jpg_for_single_jpg_photo(self):
        img = self._make_image("photo.jpg")
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([img])
        with patch.object(pt.filedialog, "asksaveasfilename", return_value="") as mock_dialog:
            ot._export()
        kwargs = mock_dialog.call_args[1]
        self.assertEqual(kwargs["defaultextension"], ".jpg")
        self.assertEqual(kwargs["initialfile"], "output.jpg")

    def test_export_dialog_defaults_to_png_for_single_png_photo(self):
        img = self._make_image("photo.png")
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([img])
        with patch.object(pt.filedialog, "asksaveasfilename", return_value="") as mock_dialog:
            ot._export()
        kwargs = mock_dialog.call_args[1]
        self.assertEqual(kwargs["defaultextension"], ".png")
        self.assertEqual(kwargs["initialfile"], "output.png")

    def test_export_dialog_still_defaults_to_pdf_for_normal_pdf(self):
        pdf_path = os.path.join(self.tmpdir, "regular.pdf")
        make_pdf(pdf_path, sizes=((595.28, 841.89),))
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([pdf_path])
        with patch.object(pt.filedialog, "asksaveasfilename", return_value="") as mock_dialog:
            ot._export()
        kwargs = mock_dialog.call_args[1]
        self.assertEqual(kwargs["defaultextension"], ".pdf")

    def test_export_dialog_defaults_to_pdf_when_multiple_pages(self):
        """사진이어도 여러 페이지가 섞여 있으면(예: PDF와 같이 사용) 굳이
        이미지 형식을 기본값으로 강제하지 않고 PDF로 유지한다."""
        img = self._make_image("photo2.jpg")
        pdf_path = os.path.join(self.tmpdir, "another.pdf")
        make_pdf(pdf_path, sizes=((595.28, 841.89),))
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([img, pdf_path])
        self.assertEqual(len(ot.pages), 2)
        with patch.object(pt.filedialog, "asksaveasfilename", return_value="") as mock_dialog:
            ot._export()
        kwargs = mock_dialog.call_args[1]
        self.assertEqual(kwargs["defaultextension"], ".pdf")


# ══════════════════════════════════════════════════════════
#  9. 텍스트/도형 복사·붙여넣기 (Ctrl+C / Ctrl+V)
# ══════════════════════════════════════════════════════════
class TestCopyPasteAnnots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = pt.TkinterDnD.Tk() if pt.DND_OK else pt.tk.Tk()
        cls.root.withdraw()
        cls.tmpdir = tempfile.mkdtemp(prefix="pdftool_copypaste_test_")
        cls.pdf_path = os.path.join(cls.tmpdir, "sample.pdf")
        make_pdf(cls.pdf_path, sizes=((595.28, 841.89), (595.28, 841.89)))

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _make_pages(self):
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([self.pdf_path])
        return ot.pages

    def _open_preview(self, pages, start=0):
        pw = pt.PreviewWin(self.root, pages, start)
        pw.update_idletasks(); pw.geometry("1150x820+0+0"); pw.update(); pw._show()
        self.addCleanup(pw.destroy)
        pw._toggle_edit()
        return pw

    def _drag_create(self, pw, tool, p0, p1):
        pw._set_tool(tool)
        pw._on_canvas_press(FakeEvent(x=p0[0], y=p0[1]))
        pw._on_canvas_motion(FakeEvent(x=p1[0], y=p1[1]))
        pw._on_canvas_release(FakeEvent(x=p1[0], y=p1[1]))

    def test_copy_paste_text_creates_identical_copy_at_same_position(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._set_tool("text")
        pw._on_canvas_press(FakeEvent(x=300, y=300))
        orig = pages[0]["annots"][0]
        orig["text"] = "복사할 텍스트"
        orig["font_size"] = 22.0
        orig["color"] = "#0000FF"
        orig["align"] = "center"
        pw._select_annot(orig["id"])

        pw._copy_selected_annot()
        pw._paste_annot()

        self.assertEqual(len(pages[0]["annots"]), 2)
        pasted = pages[0]["annots"][1]
        self.assertNotEqual(pasted["id"], orig["id"])
        self.assertEqual(pasted["x"], orig["x"])
        self.assertEqual(pasted["y"], orig["y"])
        self.assertEqual(pasted["text"], orig["text"])
        self.assertEqual(pasted["font_size"], orig["font_size"])
        self.assertEqual(pasted["color"], orig["color"])
        self.assertEqual(pasted["align"], orig["align"])
        self.assertEqual(pw.selected_id, pasted["id"])   # 붙여넣은 게 바로 선택됨

    def test_copy_paste_rect_preserves_size_and_style(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (300, 300), (450, 400))
        orig = pages[0]["annots"][0]
        orig["line_color"] = "#00FF00"
        orig["fill_enabled"] = True
        orig["fill_color"] = "#123456"
        pw._select_annot(orig["id"])

        pw._copy_selected_annot()
        pw._paste_annot()

        pasted = pages[0]["annots"][1]
        self.assertEqual(pasted["x0"], orig["x0"]); self.assertEqual(pasted["y0"], orig["y0"])
        self.assertEqual(pasted["x1"], orig["x1"]); self.assertEqual(pasted["y1"], orig["y1"])
        self.assertEqual(pasted["line_color"], orig["line_color"])
        self.assertEqual(pasted["fill_enabled"], orig["fill_enabled"])
        self.assertEqual(pasted["fill_color"], orig["fill_color"])

    def test_paste_creates_independent_copy_not_shared_reference(self):
        """붙여넣은 뒤 원본을 수정해도 복사본은 영향받으면 안 된다."""
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._set_tool("text")
        pw._on_canvas_press(FakeEvent(x=300, y=300))
        orig = pages[0]["annots"][0]
        pw._select_annot(orig["id"])
        pw._copy_selected_annot()
        pw._paste_annot()
        pasted = pages[0]["annots"][1]

        orig["text"] = "원본만 바뀜"
        self.assertNotEqual(pasted["text"], "원본만 바뀜")

    def test_paste_without_prior_copy_does_nothing(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self.assertIsNone(pw._clipboard_annot)
        pw._paste_annot()   # 예외 없이 조용히 무시되어야 함
        self.assertEqual(pages[0]["annots"], [])

    def test_copy_with_nothing_selected_does_nothing(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._select_annot(None)
        pw._copy_selected_annot()
        self.assertIsNone(pw._clipboard_annot)

    def test_paste_onto_different_page_works(self):
        """복사한 뒤 다른 페이지로 이동해서 붙여넣어도 그 페이지에
        생성되어야 한다."""
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._set_tool("text")
        pw._on_canvas_press(FakeEvent(x=300, y=300))
        orig = pages[0]["annots"][0]
        pw._select_annot(orig["id"])
        pw._copy_selected_annot()

        pw._go(1)
        self.assertEqual(pw.idx, 1)
        pw._paste_annot()

        self.assertEqual(len(pages[0]["annots"]), 1)   # 원본 페이지는 그대로
        self.assertEqual(len(pages[1]["annots"]), 1)   # 새 페이지에 붙여넣어짐
        self.assertEqual(pages[1]["annots"][0]["text"], orig["text"])

    def test_copy_paste_shortcuts_are_guarded_by_entry_focus_check(self):
        """속성 패널 입력창에 포커스가 있을 때는 Ctrl+C/V 가 도형 복사가
        아니라 그 입력창의 기본 동작(텍스트 복사/붙여넣기)으로 남아야
        한다 — Delete/방향키와 동일한 _focus_in_entry() 가드 패턴을 그대로
        재사용하는지 확인."""
        pages = self._make_pages()
        pw = self._open_preview(pages)
        self._drag_create(pw, "rect", (300, 300), (450, 400))
        entry = pt.tk.Entry(pw)
        self.addCleanup(entry.destroy)
        with patch.object(pw, "focus_get", return_value=entry):
            self.assertTrue(pw._focus_in_entry(),
                "입력창에 포커스가 있으면 _focus_in_entry() 가 True 여야 Ctrl+C/V 단축키가 가로채지 않음")


class TestPanToolAndSpacebar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = pt.TkinterDnD.Tk() if pt.DND_OK else pt.tk.Tk()
        cls.root.withdraw()
        cls.tmpdir = tempfile.mkdtemp(prefix="pdftool_pan_test_")
        cls.pdf_path = os.path.join(cls.tmpdir, "sample.pdf")
        make_pdf(cls.pdf_path, sizes=((595.28, 841.89),))

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _make_pages(self):
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        ot._load_pdfs([self.pdf_path])
        return ot.pages

    def _open_preview(self, pages, start=0):
        pw = pt.PreviewWin(self.root, pages, start)
        pw.update_idletasks(); pw.geometry("1150x820+0+0"); pw.update(); pw._show()
        self.addCleanup(pw.destroy)
        pw._toggle_edit()
        return pw

    def _finish_release(self, pw):
        """스페이스 릴리즈는 자동반복 오탐 방지를 위해 after() 로 지연 처리되므로,
        테스트에서는 예약된 콜백을 취소하고 즉시 직접 호출해 결정적으로 검증한다."""
        if pw._space_hold_pending is not None:
            pw.after_cancel(pw._space_hold_pending)
        pw._finish_space_release()

    def test_pan_button_toggles_on_and_off(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._set_tool("text")
        pw._toggle_pan_tool()
        self.assertEqual(pw.tool, "pan")
        self.assertTrue(pw._pan_active)
        pw._toggle_pan_tool()
        self.assertEqual(pw.tool, "text")
        self.assertFalse(pw._pan_active)

    def test_pan_button_highlighted_when_active(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._toggle_pan_tool()
        self.assertEqual(str(pw.tool_btns["pan"].cget("bg")), pt.ACCENT)
        self.assertEqual(str(pw.tool_btns["select"].cget("bg")), pt.TOOLBAR)

    def test_space_hold_temporarily_activates_pan_then_restores_previous_tool(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._set_tool("rect")
        pw._on_space_press(None)
        self.assertEqual(pw.tool, "pan")
        self.assertTrue(pw._pan_active)
        pw._on_space_release(None)
        self._finish_release(pw)
        self.assertEqual(pw.tool, "rect")
        self.assertFalse(pw._pan_active)

    def test_space_tap_turns_off_button_toggled_pan(self):
        """이동 버튼으로 팬을 켜둔 상태에서 스페이스바를 한 번 눌렀다
        떼면(홀드가 아니어도) 버튼을 다시 누른 것과 동일하게 꺼져야 한다."""
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._set_tool("select")
        pw._toggle_pan_tool()
        self.assertEqual(pw.tool, "pan")
        pw._on_space_press(None)
        pw._on_space_release(None)
        self._finish_release(pw)
        self.assertEqual(pw.tool, "select")
        self.assertFalse(pw._pan_active)

    def test_switching_to_another_tool_cancels_pan_state(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._toggle_pan_tool()
        self.assertTrue(pw._pan_active)
        pw._set_tool("highlight")
        self.assertFalse(pw._pan_active)
        self.assertEqual(pw.tool, "highlight")

    def test_pan_tool_drag_over_text_does_not_select_or_move_it(self):
        pages = self._make_pages()
        pw = self._open_preview(pages)
        pw._set_tool("text")
        pw._on_canvas_press(FakeEvent(x=300, y=300))
        annot = pages[0]["annots"][0]
        x0, y0 = annot["x"], annot["y"]
        pw._set_tool("select")   # 자동 전환된 도구 원복
        pw._select_annot(None)   # 선택 해제 상태에서 시작
        pw._toggle_pan_tool()
        pw._on_canvas_press(FakeEvent(x=300, y=300))
        pw._on_canvas_motion(FakeEvent(x=350, y=340))
        pw._on_canvas_release(FakeEvent(x=350, y=340))
        self.assertEqual(annot["x"], x0)
        self.assertEqual(annot["y"], y0)
        self.assertIsNone(pw.selected_id)
        self.assertEqual(pw.pan_x, 50)
        self.assertEqual(pw.pan_y, 40)


class TestUnsavedExportExitConfirmation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = pt.TkinterDnD.Tk() if pt.DND_OK else pt.tk.Tk()
        cls.root.withdraw()
        cls.tmpdir = tempfile.mkdtemp(prefix="pdftool_exit_test_")
        cls.pdf_path = os.path.join(cls.tmpdir, "sample.pdf")
        make_pdf(cls.pdf_path, sizes=((595.28, 841.89),))

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _new_tab(self):
        ot = pt.OrganizeTab(self.root)
        self.addCleanup(ot.destroy)
        return ot

    def test_no_pages_means_no_unsaved_changes(self):
        ot = self._new_tab()
        self.assertFalse(ot.has_unsaved_changes())

    def test_loading_a_file_marks_unsaved_changes(self):
        ot = self._new_tab()
        ot._load_pdfs([self.pdf_path])
        self.assertTrue(ot.has_unsaved_changes())

    def test_export_clears_unsaved_changes_flag(self):
        ot = self._new_tab()
        ot._load_pdfs([self.pdf_path])
        self.assertTrue(ot.has_unsaved_changes())
        out_path = os.path.join(self.tmpdir, "out.pdf")
        with patch.object(pt.filedialog, "asksaveasfilename", return_value=out_path), \
             patch.object(pt.messagebox, "showinfo"):
            ot._export()
        self.assertFalse(ot.has_unsaved_changes())

    def test_editing_after_export_marks_unsaved_again(self):
        ot = self._new_tab()
        ot._load_pdfs([self.pdf_path])
        out_path = os.path.join(self.tmpdir, "out.pdf")
        with patch.object(pt.filedialog, "asksaveasfilename", return_value=out_path), \
             patch.object(pt.messagebox, "showinfo"):
            ot._export()
        self.assertFalse(ot.has_unsaved_changes())
        ot._hov_action("rotate", 0)
        self.assertTrue(ot.has_unsaved_changes())

    def test_annotation_edit_via_preview_marks_unsaved(self):
        ot = self._new_tab()
        ot._load_pdfs([self.pdf_path])
        out_path = os.path.join(self.tmpdir, "out.pdf")
        with patch.object(pt.filedialog, "asksaveasfilename", return_value=out_path), \
             patch.object(pt.messagebox, "showinfo"):
            ot._export()
        self.assertFalse(ot.has_unsaved_changes())
        ot._on_preview_change()   # PreviewWin 의 on_change 콜백과 동일한 경로
        self.assertTrue(ot.has_unsaved_changes())

    def test_cancelled_export_dialog_does_not_clear_dirty_flag(self):
        ot = self._new_tab()
        ot._load_pdfs([self.pdf_path])
        with patch.object(pt.filedialog, "asksaveasfilename", return_value=""):
            ot._export()
        self.assertTrue(ot.has_unsaved_changes())


if __name__ == "__main__":
    unittest.main()
