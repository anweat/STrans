from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.shared import Inches


ROOT = Path(r"D:\zuoye\TrafficVisionAnalysis")
DOCX = ROOT / "交付文档" / "系统设计报告.docx"


def main() -> None:
    doc = Document(DOCX)

    for section in doc.sections:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width = Inches(11)
        section.page_height = Inches(8.5)
        section.left_margin = Inches(0.5)
        section.right_margin = Inches(0.5)
        section.top_margin = Inches(0.55)
        section.bottom_margin = Inches(0.5)

    max_width = Inches(9.85)
    for shape in doc.inline_shapes:
        ratio = shape.height / shape.width
        shape.width = max_width
        shape.height = int(max_width * ratio)

    doc.save(DOCX)
    print(DOCX)


if __name__ == "__main__":
    main()
