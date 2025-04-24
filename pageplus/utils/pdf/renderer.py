# SPDX-FileCopyrightText: 2023 James R. Barlow
# SPDX-License-Identifier: MPL-2.0
# Edited: 2025, Jan Kamlah

import re
from importlib import util
from math import pi

from PIL import Image
from rich import print

from pageplus.models.page import Page
from pageplus.models.text_elements import TextRegion, Textline

if (spec := util.find_spec('pikepdf')) is not None:
    from pikepdf import Matrix, Name
    from pikepdf.canvas import (
        BLUE,
        CYAN,
        MAGENTA,
        Canvas,
        Text,
        TextDirection,
        Color
    )
    from pikepdf import (
        Name,
    )
    from pageplus.utils.pdf.font import GlyphlessFont


    def page_to_pdf(page: Page,
                    image: Image = None,
                    fontname: Name = Name("/f-0-0"),
                    font: GlyphlessFont = GlyphlessFont(),
                    invisible_text: bool = True,
                    draw: list = None,
                    dpi: int = 400,
                    substitutions: list = None) -> Canvas:

        INCH = 72.0
        SCALING = INCH / dpi

        def _add_textregion(canvas: Canvas,
                            region: TextRegion):
            if draw and 'region' in draw:
                with canvas.do.save_state():
                    # draw box around paragraph
                    canvas.do.stroke_color(CYAN).line_width(0.2)
                    region_bbx = region.get_coordinates(returntype='mrr').bounds
                    canvas.do.rect(int(region_bbx[0]*SCALING),
                                   int(region_bbx[1]*SCALING),
                                   int((region_bbx[2] - region_bbx[0])*SCALING),
                                   int((region_bbx[3] - region_bbx[1])*SCALING),
                                   fill=False)
            for line in region.textlines:
                direction = line.get_reading_direction()
                direction = TextDirection(1) if direction is None or direction != 'left-to-right' else TextDirection(2)
                _add_line(canvas,
                          line,
                          direction)

        def _add_line(canvas: Canvas,
            line: Textline | None,
            text_direction: TextDirection = TextDirection(1)):
            """
            Render the textline
            """
            line_mrr = line.get_coordinates(returntype='mrr')
            line_bbox = [x*SCALING for x in line_mrr.bounds]
            height = abs(line_bbox[3] - line_bbox[1])
            width = abs(line_bbox[2] - line_bbox[0])
            if not line_bbox:
                return

            line_text = line.get_text()
            if substitutions:
                for (pattern, replacement) in substitutions:
                    re.sub(rf'{pattern}', rf'{replacement}', line_text)

            if (line_bbox[0], line_bbox[1]) == (line_bbox[2], line_bbox[3]):
                print("line box is invalid so we cannot render it: box=%s text=%s",
                    line_bbox,
                    line_text)
                return

            if draw and 'line' in draw:
                with canvas.do.save_state():
                    canvas.do.stroke_color(BLUE).line_width(0.15).rect(
                        line_bbox[0], line_bbox[1], width, height, fill=False
                    )
            if draw and 'baseline' in draw:
                baseline_tuple = line.get_baseline_coordinates(returntype='tuple')
                baseline_points = [int(baseline_tuple[0][0]*SCALING),
                                   int(baseline_tuple[0][1]*SCALING),
                                   int(baseline_tuple[-1][0]*SCALING),
                                   int(baseline_tuple[-1][1]*SCALING)]
                canvas.do.stroke_color(MAGENTA).line_width(0.25).line(*baseline_points)



            angle = 0 #line.angle()
            line_matrix = (
                Matrix()
                .translated(line_bbox[0], line_bbox[3])
                .scaled(1, -1)
                .rotated(angle / pi * 180)
            )
            with canvas.do.save_state(cm=line_matrix):
                text = Text(direction=text_direction)
                #line_box_height = abs(height) #/ cos(angle)
                fontsize = font.calculate_fontsize(line_text,width)
                text.font(fontname, fontsize)
                text.render_mode(0 if draw is None or not draw else 1)
                text._cs.show_text(line_text.encode("utf-16be"))
                # TODO: Add words?
                #for word in line.words:
                #    _add_word()
                if draw is None or not draw or 'word' in draw:
                    canvas.do.fill_color(Color(1, 1, 1, 0)).draw_text(text)

        # MAIN Function

        # create the PDF file
        # page size in points (1/72 in.)
        width, height = page.page_size()
        canvas = Canvas(page_size=(width * SCALING, height * SCALING))
        canvas.add_font(fontname, font)

        page_matrix = (
            Matrix()
            .translated(0, height*SCALING)
            .scaled(1, -1)
        )

        # draw = ['region','line','baseline']
        # Put the image in the background
        if image is not None and (draw is not None and draw):
            canvas.do.draw_image(image, 0, 0, width=width * SCALING, height=height * SCALING)
        with canvas.do.save_state(cm=page_matrix):
            for region in page.get_ordered_regions():
                region_tag = region.get_localname()
                if region_tag in ['TextRegion', 'TableRegion']:
                    _add_textregion(canvas, region)
        # Put the image in the foreground
        if image is not None and (draw is None or not draw):
            canvas.do.draw_image(image, 0, 0, width=width * SCALING, height=height * SCALING)

        return canvas
