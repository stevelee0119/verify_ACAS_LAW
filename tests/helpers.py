"""테스트용 문서 생성 헬퍼 (제24.1장 Benchmark Dataset 대응)."""
from __future__ import annotations

import zipfile
from pathlib import Path

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_docx(path: Path, body_xml: str, *, comments_xml: str | None = None, core_xml: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        zf.writestr(
            "word/document.xml",
            f'<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>{body_xml}</w:body></w:document>',
        )
        if comments_xml:
            zf.writestr(
                "word/comments.xml",
                f'<?xml version="1.0"?><w:comments xmlns:w="{W_NS}">{comments_xml}</w:comments>',
            )
        if core_xml:
            zf.writestr("docProps/core.xml", core_xml)
    return path


def make_pdf(path: Path, lines, *, hidden=None, tiny=None, metadata=None, black_box_over=None) -> Path:
    """텍스트 PDF를 만든다. hidden은 흰색, tiny는 초소형 글꼴로 그린다."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    try:
        pdfmetrics.getFont("HYSMyeongJo-Medium")
    except Exception:
        pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))

    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("HYSMyeongJo-Medium", 11)
    y = 780
    positions = {}
    for line in lines:
        c.drawString(70, y, line)
        positions[line] = y
        y -= 22
    if hidden:
        c.setFillColorRGB(1, 1, 1)
        for line in hidden:
            c.drawString(70, y, line)
            y -= 22
        c.setFillColorRGB(0, 0, 0)
    if tiny:
        c.setFont("HYSMyeongJo-Medium", 2)
        for line in tiny:
            c.drawString(70, y, line)
            y -= 12
        c.setFont("HYSMyeongJo-Medium", 11)
    if black_box_over:
        target_y = positions.get(black_box_over)
        if target_y is not None:
            c.setFillColorRGB(0, 0, 0)
            c.rect(65, target_y - 4, 420, 20, fill=1, stroke=0)
    for key, value in (metadata or {}).items():
        getattr(c, f"set{key}")(value)
    c.save()
    return path


