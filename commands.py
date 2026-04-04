"""
绘制命令
将display list中各个绘制信息转换为绘制命令
"""

from rect import Rect


class DrawText:
    # (x1, y1)为相对于canvas的坐标
    def __init__(self, x1, y1, text, font, color):
        self.left = x1
        self.top = y1
        self.text = text
        self.font = font
        self.color = color

        height = font.metrics("linespace")
        width = font.measure(self.text)
        self.rect = Rect(self.left, self.top, self.left + width, self.top + height)

        # 表示当前行的底部纵坐标，用于判断绘制位置是否位于canvas的可见区域外
        self.bottom = y1 + font.metrics("linespace")

    # scroll: 已向上滚动的距离
    def execute(self, scroll, canvas):
        canvas.create_text(
            self.left,
            self.top - scroll,
            text=self.text,
            font=self.font,
            anchor="nw",
            fill=self.color,
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
        canvas.create_rectangle(
            self.rect.left,
            self.rect.top - scroll,
            self.rect.right,
            self.rect.bottom - scroll,
            width=0,  # no default border
            fill=self.color,
        )


class DrawOutline:
    """绘制矩形区域，仅有边框，没有内部填充颜色"""

    def __init__(self, rect, color, thickness):
        self.rect = rect
        self.color = color
        self.thickness = thickness

    def execute(self, scroll, canvas):
        canvas.create_rectangle(
            self.rect.left,
            self.rect.top - scroll,
            self.rect.right,
            self.rect.bottom - scroll,
            width=self.thickness,
            outline=self.color,
        )


class DrawLine:
    """绘制直线"""

    def __init__(self, x1, y1, x2, y2, color, thickness):
        self.rect = Rect(x1, y1, x2, y2)
        self.color = color
        self.thickness = thickness

    def execute(self, scroll, canvas):
        canvas.create_line(
            self.rect.left,
            self.rect.top - scroll,
            self.rect.right,
            self.rect.bottom - scroll,
            fill=self.color,
            width=self.thickness,
        )
