# 表示浏览器框架内各个控件的矩形区域
class Rect:
    # left, top, right, bottom：在左上角坐标(left, top)以及右下角坐标(right, bottom)绘制矩形区域
    # 坐标均相对于
    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom
