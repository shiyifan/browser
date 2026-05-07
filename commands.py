"""
绘制命令
将display list中各个绘制信息转换为绘制命令
"""

from skia import Path, Paint, Rect, RRect, BlendMode
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
        self.rect = Rect.MakeLTRB(
            self.left, self.top, self.left + width, self.top + height
        )

        # 表示当前行的底部纵坐标，用于判断绘制位置是否位于canvas的可见区域外
        self.bottom = self.top + height

    def execute(self, canvas):
        paint = Paint(AntiAlias=True, Color=parse_color(self.color))

        # skia的font ascent是负值，而descent是正值，所以这里采用减法来计算baseline的纵坐标
        baseline = self.rect.top() - self.font.getMetrics().fAscent

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
    def execute(self, canvas):
        paint = Paint(Color=parse_color(self.color))
        canvas.drawRect(self.rect, paint)


class DrawRRect:
    """绘制圆角矩形区域，仅有内部填充颜色，没有边框"""

    def __init__(self, rect, radius, color):
        self.rect = rect
        self.rrect = RRect.MakeRectXY(self.rect, radius, radius)
        self.color = color

    def execute(self, canvas):
        paint = Paint(Color=parse_color(self.color), AntiAlias=True)
        canvas.drawRRect(self.rrect, paint)


class DrawOutline:
    """绘制矩形区域，仅有边框，没有内部填充颜色"""

    def __init__(self, rect, color, thickness):
        self.rect = rect
        self.color = color
        self.thickness = thickness

    def execute(self, canvas):
        paint = Paint(
            Color=parse_color(self.color),
            StrokeWidth=self.thickness,
            Style=Paint.kStroke_Style,
        )
        canvas.drawRect(self.rect, paint)


class DrawLine:
    """绘制直线"""

    def __init__(self, x1, y1, x2, y2, color, thickness):
        self.rect = Rect.MakeLTRB(x1, y1, x2, y2)
        self.color = color
        self.thickness = thickness

    def execute(self, canvas):
        path = (
            Path()
            .moveTo(self.rect.left(), self.rect.top())
            .lineTo(self.rect.right(), self.rect.bottom())
        )
        paint = Paint(
            Color=parse_color(self.color),
            StrokeWidth=self.thickness,
            Style=Paint.kStroke_Style,
        )
        canvas.drawPath(path, paint)


# "opacity"效果的绘制命令。
#
# 在当前的canvas中新建一个子surface并在其中绘制子结点的内容，然后将新surface中的内容以
# 指定的"opacity"值混合(blend)至当前canvas中
class Opacity:
    def __init__(self, opacity, children):
        self.opacity = opacity

        # 所有需要应用opacity的结点(当前结点与子结点)的绘制命令
        self.children = children

        # 表示所有子结点的区域，在这个区域上应用opacity效果
        self.rect = Rect.MakeEmpty()

        for cmd in self.children:
            self.rect.join(cmd.rect)

    def execute(self, canvas):
        paint = Paint(Alphaf=self.opacity)
        canvas.saveLayer(None, paint)  # 新建子surface

        for cmd in self.children:
            cmd.execute(canvas)

        canvas.restore()  # 将子surface中的内容blend至canvas中


# "mix-blend-mode"效果的绘制命令
class Blend:
    def __init__(self, blend_mode, children):
        self.blend_mode = blend_mode
        self.children = children

        self.rect = Rect.MakeEmpty()
        for cmd in self.children:
            self.rect.join(cmd.rect)

    def execute(self, canvas):
        paint = Paint(BlendMode=parse_blend_mode(self.blend_mode))
        canvas.saveLayer(None, paint)

        for cmd in self.children:
            cmd.execute(canvas)

        canvas.restore()


# 将CSS中的"mix-blend-mode"属性值转换为skia中的枚举值
def parse_blend_mode(blend_mode):
    if blend_mode == "multiply":
        return BlendMode.kMultiply
    elif blend_mode == "difference":
        return BlendMode.kDifference
    else:
        return BlendMode.kSrcOver
