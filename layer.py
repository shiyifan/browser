from skia import *
import const
from commands import DrawOutline
from utils import local_to_absolute


# 用于单一PaintCommand绘制时单独的Surface
class CompositedLayer:

    def __init__(self, skia_context, display_item):
        self.skia_context = skia_context
        self.surface = None  # 用于当前PaintCommand的单独的Surface
        self.display_items = [display_item]

    # 根据绘制命令在单独的Surface中绘制
    def raster(self):
        bounds = self.composited_bounds()
        if bounds.isEmpty():
            return
        irect = bounds.roundOut()

        if not self.surface:
            self.surface = Surface.MakeRenderTarget(
                self.skia_context,
                Budgeted.kNo,
                ImageInfo.MakeN32Premul(irect.width(), irect.height()),
            )
            assert self.surface

        canvas = self.surface.getCanvas()

        canvas.clear(ColorTRANSPARENT)
        canvas.save()

        if const.SHOW_COMPOSITED_LAYER_BORDERS:
            # 如果启用，则绘制layer的边界以便于调试

            border_rect = Rect.MakeXYWH(1, 1, irect.width() - 2, irect.height() - 2)
            DrawOutline(border_rect, "red", 1).execute(canvas)

        canvas.translate(-bounds.left(), -bounds.top())
        for item in self.display_items:
            item.execute(canvas)
        canvas.restore()

    # 计算绘制命令的绘制区域大小
    def composited_bounds(self):
        rect = Rect.MakeEmpty()
        for item in self.display_items:
            rect.join(item.rect)
        rect.outset(1, 1)  # for some tricky corner cases
        return rect

    # 返回绘制命令在应用css"transform"效果之后的绘制区域
    def absolute_bounds(self):
        rect = Rect.MakeEmpty()
        for item in self.display_items:
            rect.join(local_to_absolute(item, item.rect))
        return rect

    def add(self, display_item):
        self.display_items.append(display_item)

    def can_merge(self, display_item):
        return display_item.parent == self.display_items[0].parent
