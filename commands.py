"""
绘制命令
将display list中各个绘制信息转换为绘制命令
"""

from skia import Path, Paint, Rect, RRect, BlendMode
from utils import parse_color, map_translation
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

        # 该effect是否添加至"browser.draw_list"中（即绘制结果是否可被缓存）
        # True: paint draw list时将作为draw list中的Blend命令, 绘制结果不会被缓存
        # False: paint draw list时与其他的command一起构成一个DrawCompositedLayer作为draw list中的命令，绘制结果将被
        #        DrawCompositedLayer缓存
        self.needs_compositing = False

        # 由于display list是一个树形结构, 如果children中任意一个command添加至draw_list中，那么该结点也需要添加至draw_list中.
        self.needs_compositing = any(
            [child.needs_compositing for child in self.children if isinstance(child, VisualEffect)]
        )

        # effect本身的应用区域合并所有子命令的区域,最终该区域为effect实际影响区域
        #
        # 对于'Transform'command而言，在实例化时先translate由layout object计算的初始矩形区域作为
        # 自己的绘制区域，然后将其传入基类VisualEffect的构造函数。在VisualEffect构造函数中'self.rect'
        # 表示当前command自身以及所有children整体的绘制区域。由于children仍位于初始矩形区域, 只有
        # Transform位于translated的矩形，两个区域取并集(join)后便是'Transform'整体所在的区域.
        # 在raster 'CompositedLayer'时，这个整体的区域可正确地反映Transform所占据的区域，如下所示：
        #
        #
        #             calculated by layout object
        #        +-  +-------------------------+
        #        |   | Transform's children    | [no transform applied]
        #        |   |  rect                   |
        #        |   |                         |
        #        |   |    +--------------------------+
        #        |   |    |                    |     |
        #        |   |    |                    |     |
        #        |   +----|--------------------+     |
        #        |        |                          |
        #        |        |                          |
        #        |        |         'Transform' rect | [translated applied]
        #        +-       +--------------------------+
        #
        #            |                               |
        #            +-------------------------------+
        #             the whole composited layer area
        #
        #
        #
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

        if self.should_save:
            self.needs_compositing = True

    def execute(self, canvas):
        if self.should_save:
            paint = Paint(Alphaf=self.opacity, BlendMode=parse_blend_mode(self.blend_mode))
            canvas.saveLayer(None, paint)

        for cmd in self.children:
            cmd.execute(canvas)

        if self.should_save:
            canvas.restore()

    def map(self, rect):
        if (
            self.children
            and isinstance(self.children[-1], Blend)
            and self.children[-1].blend_mode == "destination-in"
        ):
            bounds = rect.makeOffset(0.0, 0.0)
            bounds.intersect(self.children[-1].rect)
            return bounds
        else:
            return rect
    
    def unmap(self, rect):
        return rect

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


# "transfrom"效果的绘制命令
class Transform(VisualEffect):
    def __init__(self, translation, rect, node, children):
        # 将由layout object计算的矩形区域转换为"translate"之后的矩形区域。
        # 如果这里直接采用layout object计算的矩形，那么在raster过程中'CompositedLayer'计算
        # surface的大小时（通过'CompositedLayer.composited_bound()'）, 'Transform.rect'无法正确
        # 反应translate之后的绘制区域，导致translated的内容在surface上仅能绘制出一部分.
        #
        # 注意：当某个html元素没有'opacity'以及'blend'效果时，会出现这种部分绘制的错误, 否则不会出现。因为
        # 有opacity以及'blend'效果的元素在'composite'时，'CompositedLayer'中缓存的是'Draw***'命令，
        # 'Draw***'的所有parent command均由'browser.draw()'调用绘制，且每次重绘时（非composite-raster重绘）将按照parent command
        # 中的'Transform'在root canvas中translate元素。所以不会出现这个问题。
        # 而没有上述效果的元素在'CompositedLayer'中缓存的可能是整个'Transform'. 重绘时（非composite-raster重绘）将整个
        # Transform的结果复制到root canvas上，且复制时没有translate操作（因为复制操作由'DrawCompositedLayer'完成）,
        # 所以会出现这个问题。
        #
        # 'CompositedLayer'内部的surface的大小尽可能要包含所有在屏幕上可显示的children
        trans_rect = map_translation(rect, translation)

        super().__init__(trans_rect, children, node)
        self.self_rect = trans_rect
        self.translation = translation

    def execute(self, canvas):
        if self.translation:
            x, y = self.translation
            canvas.save()
            canvas.translate(x, y)

        for cmd in self.children:
            cmd.execute(canvas)

        if self.translation:
            canvas.restore()

    def map(self, rect):
        return map_translation(rect, self.translation)
    
    def unmap(self, rect):
        return map_translation(rect, self.translation, True)

    def clone(self, child):
        return Transform(self.translation, self.self_rect, self.node, [child])

    def __repr__(self):
        if self.translation:
            x, y = self.translation
            return f"Transform(translate({x}, {y}))"
        else:
            return "Transform(<no-op>)"


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
