"""
绘制命令
将display list中各个绘制信息转换为绘制命令
"""

from skia import Path, Paint, Rect, RRect, BlendMode
from utils import parse_color
from font import linespace


# 作为所有绘制图形、字符的command的基类
# 在animation渲染过程中,该绘制命令的绘制结果可以被缓存,以便于animation的每一帧渲染
class PaintCommand:
    def __init__(self, rect):
        self.rect = rect  # 绘制的图形、字符所在的矩形区域

        # 一般情况下绘制command没有子结点，为了与"VisualEffect"保持一致，添加一个空的"children"属性
        self.children = []


# 作为所有绘制视觉效果的command的基类
# 对于基于visual effect的animation, 一般不会缓存该命令的绘制结果
class VisualEffect:
    def __init__(self, rect, children, node=None):
        self.rect = rect.makeOffset(0.0, 0.0)  # effect本身的应用区域
        self.children = children  # 所有需要应用当前effect的结点(当前结点与子结点)的绘制命令
        self.node = node  # 拥有当前effect的DOM node

        # effect本身的应用区域合并所有子命令的区域,最终该区域为effect实际影响区域
        for child in self.children:
            self.rect.join(child.rect)


class DrawText(PaintCommand):
    # (x1, y1)为相对于canvas的坐标
    def __init__(self, x1, y1, text, font, color):
        super().__init__(None)

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

    def execute(self, canvas):
        paint = Paint(AntiAlias=True, Color=parse_color(self.color))

        # skia的font ascent是负值，而descent是正值，所以这里采用减法来计算baseline的纵坐标
        baseline = self.rect.top() - self.font.getMetrics().fAscent

        canvas.drawString(self.text, float(self.rect.left()), baseline, self.font, paint)

    def __repr__(self):
        return f"{self.__class__.__name__}(text={self.text})"


class DrawRect(PaintCommand):
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

        super().__init__(rect)

        self.color = color

    # scroll: 已向上滚动的距离
    def execute(self, canvas):
        paint = Paint(Color=parse_color(self.color))
        canvas.drawRect(self.rect, paint)

    def __repr__(self):
        return f"{self.__class__.__name__}(top={self.rect.top}, \
bottom={self.rect.bottom}, right={self.rect.right}, left={self.rect.left}, \
color={self.color})"


class DrawRRect(PaintCommand):
    """绘制圆角矩形区域，仅有内部填充颜色，没有边框"""

    def __init__(self, rect, radius, color):
        super().__init__(rect)

        self.rrect = RRect.MakeRectXY(self.rect, radius, radius)
        self.color = color

    def execute(self, canvas):
        paint = Paint(Color=parse_color(self.color), AntiAlias=True)
        canvas.drawRRect(self.rrect, paint)


class DrawOutline(PaintCommand):
    """绘制矩形区域，仅有边框，没有内部填充颜色"""

    def __init__(self, rect, color, thickness):
        super().__init__(rect)

        self.color = color
        self.thickness = thickness

    def execute(self, canvas):
        paint = Paint(
            Color=parse_color(self.color),
            StrokeWidth=self.thickness,
            Style=Paint.kStroke_Style,
        )
        canvas.drawRect(self.rect, paint)


class DrawLine(PaintCommand):
    """绘制直线"""

    def __init__(self, x1, y1, x2, y2, color, thickness):
        super().__init__(Rect.MakeLTRB(x1, y1, x2, y2))

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
class Opacity(VisualEffect):
    def __init__(self, opacity, children):
        super().__init__(Rect.MakeEmpty(), children)

        self.opacity = opacity

    def execute(self, canvas):
        paint = Paint(Alphaf=self.opacity)

        if self.opacity < 1:
            # 仅在需要"不透明度"效果时才新建子surface
            canvas.saveLayer(None, paint)  # 新建子surface

        for cmd in self.children:
            cmd.execute(canvas)

        if self.opacity < 1:
            canvas.restore()  # 将子surface中的内容blend至canvas中


# "mix-blend-mode"效果以及"opacity"效果的绘制命令
class Blend(VisualEffect):
    def __init__(self, opacity, blend_mode, node, children):
        super().__init__(Rect.MakeEmpty(), children, node)

        self.opacity = opacity
        self.blend_mode = blend_mode
        # 是否需要新建子surface来应用opacity或者blend
        self.should_save = bool(self.blend_mode or self.opacity < 1)

    def execute(self, canvas):
        if self.should_save:
            paint = Paint(Alphaf=self.opacity, BlendMode=parse_blend_mode(self.blend_mode))
            canvas.saveLayer(None, paint)

        for cmd in self.children:
            cmd.execute(canvas)

        if self.should_save:
            canvas.restore()

    # 创建当前Blend对象的副本，但采用不同的子结点
    def clone(self, child):
        return Blend(self.opacity, self.blend_mode, self.node, [child])

    def __repr__(self):
        args = ""
        if self.opacity < 1:
            args += f"opacity={self.opacity}, "
        if self.blend_mode:
            args += f"blend_mode={self.blend_mode}, "
        if not args:
            args = "no-op"
        return f"{self.__class__.__name__}({args})"


class DrawCompositedLayer(PaintCommand):
    def __init__(self, composited_layer):
        super().__init__(composited_layer.composited_bounds())
        self.composited_layer = composited_layer

    def execute(self, canvas):
        layer = self.composited_layer
        bounds = layer.composited_bounds()
        layer.surface.draw(canvas, bounds.left(), bounds.top())

    def __repr__(self):
        return "DrawCompositedLayer()"


# 将CSS中的"mix-blend-mode"属性值转换为skia中的枚举值
def parse_blend_mode(blend_mode):
    if blend_mode == "multiply":
        return BlendMode.kMultiply
    elif blend_mode == "difference":
        return BlendMode.kDifference
    elif blend_mode == "destination-in":
        return BlendMode.kDstIn
    elif blend_mode == "source-over":
        return BlendMode.kSrcOver
    else:
        return BlendMode.kSrcOver
