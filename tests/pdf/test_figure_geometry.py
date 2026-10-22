"""真实 PDF 图像对象和矢量路径的定位回归，不依赖翻译模型。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject, RectangleObject, ArrayObject, FloatObject

from easyread.pdf import figure_geometry, pdfwork
from easyread.library.store import write_json_atomic


def make_pdf(path, images=(), paths=(), words=(), rotation=0, fills=(), framed=(), white_words=(), clipped=()):
    """fills：只填充不描边的矩形 (框, 灰度)；framed：四周带白边的图片（内容占中间）；
    white_words：白色（看不见）的字；clipped：被裁剪路径整个挡住的描边矩形。"""
    writer = PdfWriter()
    page = writer.add_blank_page(width=500, height=700)
    xobjects = DictionaryObject()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): xobjects,
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    commands = []
    for (x0, y0, x1, y1), gray in fills:  # 背景先画
        commands.append(f"q {gray} g {x0 * 500} {(1-y1) * 700} {(x1-x0) * 500} {(y1-y0) * 700} re f Q")
    for i, (x0, y0, x1, y1) in enumerate(images):
        image = DecodedStreamObject()
        image.set_data(bytes([30, 90, 150]) * 4)
        image.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                      NameObject("/Width"): NumberObject(2), NameObject("/Height"): NumberObject(2),
                      NameObject("/ColorSpace"): NameObject("/DeviceRGB"), NameObject("/BitsPerComponent"): NumberObject(8)})
        name = f"/Im{i}"
        xobjects[NameObject(name)] = writer._add_object(image)
        commands.append(f"q {(x1 - x0) * 500} 0 0 {(y1 - y0) * 700} {x0 * 500} {(1 - y1) * 700} cm {name} Do Q")
    for i, (x0, y0, x1, y1) in enumerate(framed):
        # 10x10 像素：上 3 行、下 1 行、左右各 1 列是白边，中间是深色内容。
        pixels = bytes(v for r in range(10) for c in range(10)
                       for v in ((255, 255, 255) if r < 3 or r > 8 or c < 1 or c > 8 else (30, 90, 150)))
        image = DecodedStreamObject()
        image.set_data(pixels)
        image.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                      NameObject("/Width"): NumberObject(10), NameObject("/Height"): NumberObject(10),
                      NameObject("/ColorSpace"): NameObject("/DeviceRGB"), NameObject("/BitsPerComponent"): NumberObject(8)})
        name = f"/Fr{i}"
        xobjects[NameObject(name)] = writer._add_object(image)
        commands.append(f"q {(x1 - x0) * 500} 0 0 {(y1 - y0) * 700} {x0 * 500} {(1 - y1) * 700} cm {name} Do Q")
    for x0, y0, x1, y1 in clipped:
        commands.append(f"q 0 0 1 1 re W n {x0 * 500} {(1-y1) * 700} {(x1-x0) * 500} {(y1-y0) * 700} re S Q")
    for x0, y0, x1, y1 in paths:
        commands.append(f"{x0 * 500} {(1-y1) * 700} {(x1-x0) * 500} {(y1-y0) * 700} re S")
    for text, x, y in words:
        commands.append(f"BT /F1 10 Tf 1 0 0 1 {x * 500} {(1-y) * 700} Tm ({text}) Tj ET")
    for text, x, y in white_words:
        commands.append(f"q 1 g BT /F1 10 Tf 1 0 0 1 {x * 500} {(1-y) * 700} Tm ({text}) Tj ET Q")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    if rotation:
        page.rotate(rotation)
    writer.write(path)


def loc(box, src="text"):
    return {"page": 1, "box": list(box), "src": src}


def make_tiled_pdf(path, *, scaled=False):
    """A page-sized wrapper references a shared canvas ten pages tall."""
    writer = PdfWriter()
    shared = DecodedStreamObject()
    shared.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                   NameObject("/BBox"): RectangleObject([0, 0, 300, 3000]),
                   NameObject("/Resources"): DictionaryObject()})
    shared.set_data(b"20 2450 200 100 re S 20 450 200 100 re S")
    if scaled:
        shared[NameObject("/Matrix")] = ArrayObject([FloatObject(v) for v in [.05, 0, 0, .05, 0, 0]])
    wrapper = DecodedStreamObject()
    wrapper.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                    NameObject("/BBox"): RectangleObject([0, 2250, 300, 2550]),
                    NameObject("/Matrix"): ArrayObject([FloatObject(v) for v in [1, 0, 0, 1, 0, -2250]]),
                    NameObject("/Resources"): DictionaryObject({NameObject("/XObject"): DictionaryObject({
                        NameObject("/Shared"): writer._add_object(shared)})})})
    wrapper.set_data(b"/Shared Do")
    page = writer.add_blank_page(width=300, height=300)
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): DictionaryObject({
        NameObject("/Tile"): writer._add_object(wrapper)})})
    stream = DecodedStreamObject()
    stream.set_data(b"/Tile Do")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)


class FigureGeometryTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def extend(self, blocks, layout, **pdf):
        make_pdf(self.root / "source.pdf", **pdf)
        pdfwork._extend_captioned(blocks, layout, self.root)
        return layout

    def test_side_caption_keeps_left_and_lower_panels_despite_overestimated_paragraph(self):
        image = [.08, .36, .60, .86]
        layout = {"body": loc([.08, .10, .93, .90]), "fig": loc([.73, .56, .91, .69])}
        self.extend([{"id": "fig", "type": "figure"}], layout, images=[image])
        box = layout["fig"]["box"]
        self.assertEqual(layout["fig"]["src"], "graphic")
        self.assertLess(box[0], image[0])
        self.assertLess(box[1], image[1])
        self.assertGreater(box[2], .91)
        self.assertGreater(box[3], image[3])
        pdfwork._clamp_overlaps(layout)
        self.assertEqual(layout["fig"]["box"], box)

    def test_two_figures_on_same_page_stay_separate(self):
        layout = {"left": loc([.08, .72, .46, .77]), "right": loc([.54, .72, .92, .77])}
        blocks = [{"id": bid, "type": "figure"} for bid in layout]
        self.extend(blocks, layout, images=[[.08, .30, .46, .70], [.54, .30, .92, .70]])
        self.assertLess(layout["left"]["box"][2], .5)
        self.assertGreater(layout["right"]["box"][0], .5)
        self.assertTrue(all(l["src"] == "graphic" for l in layout.values()))

    def test_separate_subpanel_images_are_kept_without_publisher_logo(self):
        layout = {"fig": loc([.1, .72, .9, .77])}
        self.extend([{"id": "fig", "type": "figure"}], layout,
                    images=[[.1, .30, .46, .70], [.54, .30, .9, .70], [.08, .01, .22, .05]])
        self.assertEqual(layout["fig"]["src"], "graphic")
        self.assertAlmostEqual(layout["fig"]["box"][1], .292)
        self.assertLess(layout["fig"]["box"][0], .1)
        self.assertGreater(layout["fig"]["box"][2], .9)

    def test_caption_above_drawing(self):
        layout = {"fig": loc([.1, .20, .45, .25])}
        self.extend([{"id": "fig", "type": "figure", "caption_pos": "above"}], layout,
                    images=[[.1, .27, .45, .65]])
        self.assertEqual(layout["fig"]["src"], "graphic")
        self.assertGreater(layout["fig"]["box"][3], .65)

    def test_distant_top_row_is_connected_through_lower_panels(self):
        for kind in ("images", "paths"):
            with self.subTest(kind=kind):
                layout = {"fig": loc([.1, .7, .9, .75])}
                panels = [[.1, .08, .45, .26], [.55, .08, .9, .26],
                          [.1, .30, .45, .48], [.55, .30, .9, .48],
                          [.1, .52, .45, .67], [.55, .52, .9, .67]]
                self.extend([{"id": "fig", "type": "figure"}], layout, **{kind: panels})
                self.assertEqual(layout["fig"]["src"], "graphic")
                self.assertLess(layout["fig"]["box"][1], .08)

    def test_vector_plot_keeps_label_and_ignores_caption_background_and_footer(self):
        layout = {"fig": loc([.1, .72, .48, .77])}
        self.extend([{"id": "fig", "type": "figure"}], layout,
                    paths=[[.12, .30, .48, .68], [.095, .715, .485, .775], [.03, .91, .97, .91]],
                    words=[("axis", .1, .68), ("Figure 1", .1, .74)])
        self.assertEqual(layout["fig"]["src"], "graphic")
        self.assertLess(layout["fig"]["box"][0], .1)
        self.assertLess(layout["fig"]["box"][3], .8)

    def test_full_page_scan_and_inline_formula_use_existing_fallback(self):
        layout = {"body": loc([.1, .1, .9, .35]), "fig": loc([.1, .7, .9, .75])}
        self.extend([{"id": "fig", "type": "figure"}], layout,
                    images=[[0, 0, 1, 1], [.2, .2, .35, .24]])
        self.assertEqual(layout["fig"]["src"], "caption")
        self.assertAlmostEqual(layout["fig"]["box"][1], .355)

    def test_explicit_manual_box_and_table_are_preserved(self):
        layout = {"fig": loc([.1, .3, .5, .8], "manual"), "table": loc([.55, .7, .9, .75])}
        self.extend([{"id": "fig", "type": "figure", "box": [.1, .3, .5, .8]},
                     {"id": "table", "type": "table"}], layout,
                    images=[[.05, .2, .52, .9], [.55, .3, .9, .68]])
        self.assertEqual(layout["fig"], loc([.1, .3, .5, .8], "manual"))
        self.assertEqual(layout["table"]["src"], "caption")

    def test_manual_figures_do_not_open_pdf_layout_or_preflight(self):
        make_pdf(self.root / "source.pdf", images=[[.05, .2, .52, .9]])
        box = [.1, .3, .5, .8]
        blocks = [{"id": "fig", "type": "figure", "box": box, "src": "figures/saved.webp"}]
        layout = {"fig": loc(box, "manual")}
        with patch("pdfplumber.open") as opened, patch("pypdf.PdfReader") as preflight:
            pdfwork._extend_captioned(blocks, layout, self.root)
        opened.assert_not_called()
        preflight.assert_not_called()
        self.assertEqual(layout["fig"], loc(box, "manual"))
        self.assertEqual(blocks[0]["src"], "figures/saved.webp")

    def test_tiled_nested_long_form_falls_back_without_pdfplumber(self):
        make_tiled_pdf(self.root / "source.pdf")
        blocks = [{"id": "fig", "type": "figure", "src": "figures/saved.webp"}]
        layout = {"body": loc([.1, .1, .9, .3]), "fig": loc([.1, .7, .9, .75])}
        with patch("pdfplumber.open") as opened:
            pdfwork._extend_captioned(blocks, layout, self.root)
        opened.assert_not_called()
        self.assertEqual(layout["fig"]["src"], "caption")
        self.assertAlmostEqual(layout["fig"]["box"][1], .305)
        self.assertEqual(blocks[0]["src"], "figures/saved.webp")

    def test_scaled_long_form_that_fits_page_is_safe(self):
        make_tiled_pdf(self.root / "source.pdf", scaled=True)
        self.assertEqual(figure_geometry._unsafe_pages(self.root / "source.pdf", [1]), set())

    def test_safe_page_geometry_still_runs_beside_tiled_page(self):
        normal, tiled = self.root / "normal.pdf", self.root / "tiled.pdf"
        make_pdf(normal, images=[[.1, .3, .45, .65]])
        make_tiled_pdf(tiled)
        writer = PdfWriter()
        writer.add_page(PdfReader(normal).pages[0])
        writer.add_page(PdfReader(tiled).pages[0])
        writer.write(self.root / "source.pdf")
        blocks = [{"id": "safe", "type": "figure"}, {"id": "tile", "type": "figure"}]
        layout = {"safe": loc([.1, .72, .45, .77]), "tile": {**loc([.1, .7, .9, .75]), "page": 2}}
        with patch.object(figure_geometry, "_page_regions", wraps=figure_geometry._page_regions) as regions:
            pdfwork._extend_captioned(blocks, layout, self.root)
        self.assertEqual(regions.call_count, 1)
        self.assertEqual(layout["safe"]["src"], "graphic")
        self.assertEqual(layout["tile"]["src"], "caption")

    def test_page_layout_is_closed_even_when_geometry_fails(self):
        make_pdf(self.root / "normal.pdf", images=[[.1, .3, .45, .65]])
        writer = PdfWriter()
        page = PdfReader(self.root / "normal.pdf").pages[0]
        writer.add_page(page)
        writer.add_page(page)
        writer.write(self.root / "source.pdf")
        for failed in (False, True):
            with self.subTest(failed=failed):
                parsed, retained = [], []

                def regions(page, *_):
                    if parsed:
                        retained.append(hasattr(parsed[0], "_layout") or hasattr(parsed[0], "_objects"))
                    page.chars  # Populate the actual pdfplumber page cache.
                    parsed.append(page)
                    if failed and page.page_number == 1:
                        raise RuntimeError("test read failure")
                    return {}

                blocks = [{"id": "first", "type": "figure"}, {"id": "second", "type": "figure"}]
                layout = {"first": loc([.1, .72, .45, .77]), "second": {**loc([.1, .72, .45, .77]), "page": 2}}
                with patch.object(figure_geometry, "_page_regions", side_effect=regions), \
                        patch.object(figure_geometry.log, "exception"):
                    pdfwork._extend_captioned(blocks, layout, self.root)
                self.assertEqual(len(parsed), 2)
                self.assertEqual(retained, [False])  # Already closed before the next page, not just on PDF exit.

    def test_nearby_table_graphic_is_not_assigned_to_figure(self):
        layout = {"fig": loc([.1, .72, .45, .77]), "table": loc([.55, .68, .9, .71])}
        self.extend([{"id": "fig", "type": "figure"}, {"id": "table", "type": "table"}], layout,
                    images=[[.1, .3, .45, .65], [.55, .3, .9, .65]])
        self.assertEqual(layout["fig"]["src"], "graphic")
        self.assertLess(layout["fig"]["box"][2], .5)

    def test_white_background_rect_does_not_pull_body_text_below_caption(self):
        # 白色背景矩形一直铺到题注下面的正文：页面上看不见，不能把图框撑下去。
        layout = {"fig": loc([.1, .32, .9, .36]), "body": loc([.1, .42, .9, .85])}
        self.extend([{"id": "fig", "type": "figure"}], layout, images=[[.3, .12, .7, .3]],
                    fills=[([.2, .1, .8, .9], 1)], words=[("body", .1, .45)])
        box = layout["fig"]["box"]
        self.assertEqual(layout["fig"]["src"], "graphic")
        self.assertGreater(box[1], .1)
        self.assertLess(box[3], .38)

    def test_white_background_rect_does_not_reach_header(self):
        layout = {"fig": loc([.1, .32, .9, .36])}
        self.extend([{"id": "fig", "type": "figure"}], layout, images=[[.3, .12, .7, .3]],
                    fills=[([.06, 0, .94, .31], 1)], words=[("Journal of Tests", .1, .04)])
        self.assertGreater(layout["fig"]["box"][1], .1)

    def test_clipped_drawing_is_ignored(self):
        layout = {"fig": loc([.1, .32, .9, .36])}
        self.extend([{"id": "fig", "type": "figure"}], layout, images=[[.3, .12, .7, .3]],
                    clipped=[[.05, .07, .95, .31]])
        box = layout["fig"]["box"]
        self.assertGreater(box[1], .1)
        self.assertGreater(box[0], .09)

    def test_image_white_margin_does_not_reach_header(self):
        # 位图上方 30% 是白边，一直顶到页眉；按看得见的内容收边，页眉文字不进框。
        layout = {"fig": loc([.1, .42, .9, .46])}
        self.extend([{"id": "fig", "type": "figure"}], layout, framed=[[.1, .03, .9, .4]],
                    words=[("Journal of Tests", .1, .05)])
        box = layout["fig"]["box"]
        self.assertEqual(layout["fig"]["src"], "graphic")
        self.assertGreater(box[1], .12)

    def test_header_above_rule_is_not_a_label(self):
        layout = {"fig": loc([.1, .42, .9, .46])}
        self.extend([{"id": "fig", "type": "figure"}], layout, images=[[.1, .08, .9, .4]],
                    paths=[[.05, .058, .95, .058]], words=[("Journal of Tests", .1, .05)])
        self.assertGreater(layout["fig"]["box"][1], .065)

    def test_separated_panels_join_unless_body_text_between(self):
        panels = [[.1, .08, .9, .3], [.1, .42, .9, .66]]
        layout = {"fig": loc([.1, .7, .9, .74])}
        self.extend([{"id": "fig", "type": "figure"}], layout, images=panels)
        self.assertLess(layout["fig"]["box"][1], .08)
        layout = {"fig": loc([.1, .7, .9, .74]), "body": loc([.1, .32, .9, .4])}
        self.extend([{"id": "fig", "type": "figure"}], layout, images=panels, words=[("body", .1, .35)])
        self.assertGreater(layout["fig"]["box"][1], .4)

    def test_invisible_text_is_not_a_label(self):
        layout = {"fig": loc([.3, .62, .7, .66])}
        self.extend([{"id": "fig", "type": "figure"}], layout, images=[[.3, .3, .7, .6]],
                    white_words=[("hidden", .22, .45)])
        self.assertGreater(layout["fig"]["box"][0], .28)

    def test_labels_below_caption_do_not_extend_box(self):
        # 题注在图正下方：连到题注下面的文字（正文没定位上时）不能把框往下撑。
        layout = {"fig": loc([.1, .62, .9, .66])}
        self.extend([{"id": "fig", "type": "figure"}], layout, images=[[.1, .3, .9, .6]],
                    words=[("axis", .02, .625), ("more", .02, .655), ("text", .02, .685)])
        self.assertLess(layout["fig"]["box"][3], .67)

    def test_crop_leaves_out_caption_below(self):
        layout = {"fig": loc([.1, .62, .9, .66])}
        self.extend([{"id": "fig", "type": "figure"}], layout, images=[[.1, .3, .9, .6]],
                    words=[("Figure 1. Caption.", .1, .64)])
        fig = layout["fig"]
        self.assertGreater(fig["box"][3], .66)
        self.assertLess(fig["crop"][3], .62)
        self.assertGreater(fig["crop"][3], .6)

    def test_crop_stops_at_caption_drawn_over_image_bottom(self):
        # 图片底边的空白伸到了题注第一行下面（题注压在图片上画）：截图截到题注上沿。
        layout = {"fig": loc([.1, .6, .9, .66])}
        self.extend([{"id": "fig", "type": "figure"}], layout, images=[[.1, .3, .9, .63]])
        self.assertLessEqual(layout["fig"]["crop"][3], .6)
        self.assertGreater(layout["fig"]["box"][3], .66)

    def test_tight_model_box_grows_to_the_drawing(self):
        # Issue #45：模型只框到图的上半截，按 PDF 图形边界撑开到整张图。
        layout = {"fig": loc([.1, .72, .9, .76])}
        self.extend([{"id": "fig", "type": "figure", "page": 1, "box": [.15, .32, .85, .5]}], layout,
                    images=[[.1, .3, .9, .7]])
        fig = layout["fig"]
        self.assertEqual(fig["src"], "graphic")
        self.assertLess(fig["crop"][0], .1)
        self.assertGreater(fig["crop"][3], .7)
        self.assertLess(fig["crop"][3], .72)

    def test_model_box_picks_the_drawing_the_caption_is_not_nearest_to(self):
        # 题注离下面那张图更近，但模型框住的是上面那张：以模型认的为准，边界仍按 PDF。
        layout = {"fig": loc([.1, .47, .9, .5])}
        self.extend([{"id": "fig", "type": "figure", "page": 1, "box": [.12, .1, .88, .3]}], layout,
                    images=[[.1, .08, .9, .32], [.1, .52, .9, .8]], words=[("body", .1, .4)])
        fig = layout["fig"]
        self.assertEqual(fig["src"], "graphic")
        self.assertLess(fig["crop"][1], .08)
        self.assertLess(fig["crop"][3], .34)

    def test_model_box_is_used_when_no_drawing_is_found(self):
        for hint_page in (1, 2):
            with self.subTest(hint_page=hint_page):
                layout = {"body": loc([.1, .1, .9, .35]), "fig": loc([.1, .7, .9, .75])}
                box = [.2, .4, .8, .68]
                self.extend([{"id": "fig", "type": "figure", "page": hint_page, "box": box}], layout,
                            images=[[0, 0, 1, 1]])
                self.assertEqual(layout["fig"], {"page": hint_page, "box": box, "src": "manual"})

    def test_model_box_figure_is_still_located_by_caption(self):
        make_pdf(self.root / "source.pdf", images=[[.1, .3, .9, .65]], words=[("Figure 1. A drawing.", .1, .7)])
        box = [.15, .32, .85, .45]
        blocks = [{"id": "fig", "type": "figure", "page": 1, "box": box, "caption_en": "Figure 1. A drawing."},
                  {"id": "lone", "type": "figure", "page": 1, "box": box, "caption_en": "Not on the page."}]
        write_json_atomic(self.root / "paper.json", {"blocks": blocks})
        pdfwork.extract_text(self.root / "source.pdf", self.root / "extract")
        layout = pdfwork.locate(self.root)
        self.assertEqual(layout["fig"]["src"], "graphic")
        self.assertGreater(layout["fig"]["crop"][3], .65)
        self.assertEqual(layout["lone"], {"page": 1, "box": box, "src": "manual"})

    def test_rotated_pdf_uses_rendered_page_coordinates(self):
        for rotation, expected in ((90, [.35, .1, .7, .45]), (270, [.3, .55, .65, .9])):
            with self.subTest(rotation=rotation):
                make_pdf(self.root / "source.pdf", images=[[.1, .3, .45, .65]],
                         words=[("Figure 1. Rotated drawing.", .1, .73)], rotation=rotation)
                write_json_atomic(self.root / "paper.json", {"blocks": [
                    {"id": "fig", "type": "figure", "page": 1, "caption_en": "Figure 1. Rotated drawing."}]})
                pdfwork.extract_text(self.root / "source.pdf", self.root / "extract")
                loc = pdfwork.locate(self.root)["fig"]
                self.assertEqual(loc["src"], "graphic")
                self.assertLess(loc["box"][0], expected[0])
                self.assertLess(loc["box"][1], expected[1])
                self.assertGreater(loc["box"][2], expected[2])
                self.assertGreater(loc["box"][3], expected[3])

    def test_old_layout_refreshes_from_pdf_once_without_changing_translation(self):
        make_pdf(self.root / "source.pdf", images=[[.08, .30, .60, .86]],
                 words=[("Figure 1. A side caption.", .72, .6)])
        paper = {"blocks": [{"id": "fig", "type": "figure", "page": 1,
                             "caption_en": "Figure 1. A side caption.", "caption_zh": "保留的译文"}]}
        write_json_atomic(self.root / "paper.json", paper)
        write_json_atomic(self.root / "layout.json", {"fig": loc([.72, .30, .94, .63], "caption")})
        pdfwork.extract_text(self.root / "source.pdf", self.root / "extract")
        (self.root / "extract/locate.version").write_text("3")
        before = (self.root / "paper.json").read_bytes()
        with patch.object(pdfwork, "locate", wraps=pdfwork.locate) as locate:
            pdfwork.refresh_layout(self.root)
            pdfwork.refresh_layout(self.root)
            locate.assert_called_once_with(self.root)
        import json
        new = json.loads((self.root / "layout.json").read_text())["fig"]
        self.assertEqual(new["src"], "graphic")
        self.assertLess(new["box"][0], .08)
        self.assertGreater(new["box"][3], .86)
        self.assertEqual((self.root / "paper.json").read_bytes(), before)


class PageMarginsTest(unittest.TestCase):
    def test_running_header_and_page_number_are_detected(self):
        import json
        from easyread.pdf import page_margins
        with tempfile.TemporaryDirectory() as temp:
            extract = Path(temp)
            for pn in range(1, 5):
                chars = [[ch, .1 + i * .01, .03, .11 + i * .01, .045] for i, ch in enumerate("Journal")]
                chars += [[ch, .5 + i * .01, .95, .51 + i * .01, .96] for i, ch in enumerate(str(pn * 7))]
                chars += [["x", .1, .5, .11, .51]]
                if pn == 1:
                    chars += [[ch, .1 + i * .01, .07, .11 + i * .01, .085] for i, ch in enumerate("Title")]
                (extract / f"page-{pn:03d}.chars.json").write_text(json.dumps(chars))
            running = page_margins.running_lines(extract, 4)
            self.assertEqual(len(running[1]), 2)  # 只出现一次的标题不算页眉
            self.assertEqual(page_margins.margins([], running[1]), (.06, .94))
            self.assertEqual(page_margins.margins([[.05, .1, .95, .1]], running[1]), (.1, .94))
            self.assertEqual(page_margins.margins([], [[.1, .03, .2, .07], [.5, .92, .6, .93]]), (.07, .92))


if __name__ == "__main__":
    unittest.main()
