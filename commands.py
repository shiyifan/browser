"""
绘制命令
将display list中各个绘制信息转换为绘制命令
"""

from skia import Path, Paint, Rect
from utils import parse_color
from font import linespace


class DrawText:
    # (x1, y1)为相对于canvas的坐标
    def __init__(self, x1, y1, text, font, color):
        self.left = x1
        self.top = y1
        self.text = text
        self.font = font
        self.color = color

        height = linespace(font)
        width = font.measureText(self.text)
        self.rect = Rect.MakeLTRB(self.left, self.top, self.left + width, self.top + height)

        # 表示当前行的底部纵坐标，用于判断绘制位置是否位于canvas的可见区域外
        self.bottom = self.top + height

    # scroll: 已向上滚动的距离
    def execute(self, scroll, canvas):
        paint = Paint(AntiAlias=True, Color=parse_color(self.color))

        # skia的font ascent是负值，而descent是正值，所以这里采用减法来计算baseline的纵坐标
        baseline = self.rect.top() - scroll - self.font.getMetrics().fAscent

        canvas.drawString(
            self.text, float(self.rect.left()), baseline, self.font, paint
        )


class DrawRect:
    """绘制矩形区域，仅有内部填充颜色，没有边框"""

    # (x1, y1), (x2, y2)为相对于canvas的坐标
    # def __init__(self, x1, y1, x2, y2, color):
    #     self.top = y1
    #     self.left = x1
    #     self.bottom = y2
    #     self.right = x2
    #     self.color = color

    def __init__(self, rect, color):
        """
        根据rect绘制矩形背景

        Parameters:
            rect: 矩形区域Rect
            color: 背景颜色
        """

        self.rect = rect
        self.color = color

    # scroll: 已向上滚动的距离
    def execute(self, scroll, canvas):
        paint = Paint(Color=parse_color(self.color))
        canvas.drawRect(self.rect.makeOffset(0, -scroll), paint)


class DrawOutline:
    """绘制矩形区域，仅有边框，没有内部填充颜色"""

    def __init__(self, rect, color, thickness):
        self.rect = rect
        self.color = color
        self.thickness = thickness

    def execute(self, scroll, canvas):
        paint = Paint(
            Color=parse_color(self.color),
            StrokeWidth=self.thickness,
            Style=Paint.kStroke_Style,
        )
        canvas.drawRect(self.rect.makeOffset(0, -scroll), paint)


class DrawLine:
    """绘制直线"""

    def __init__(self, x1, y1, x2, y2, color, thickness):
        self.rect = Rect.MakeLTRB(x1, y1, x2, y2)
        self.color = color
        self.thickness = thickness

    def execute(self, scroll, canvas):
        path = (
            Path()
            .moveTo(self.rect.left(), self.rect.top() - scroll)
            .lineTo(self.rect.right(), self.rect.bottom() - scroll)
        )
        paint = Paint(
            Color=parse_color(self.color),
            StrokeWidth=self.thickness,
            Style=Paint.kStroke_Style,
        )
        canvas.drawPath(path, paint)
