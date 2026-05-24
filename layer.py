from skia import *


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
        canvas.translate(-bounds.left(), -bounds.top())
        for item in self.display_items:
            item.execute(canvas)
        canvas.restore()

    # 计算绘制命令的绘制区域大小
    def composited_bounds(self):
        rect = Rect.MakeEmpty()
        for item in self.display_items:
            rect.join(item.rect)
        rect.outset(1, 1)  # for some tricky cornor cases
        return rect
