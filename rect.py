class Rect:
    """表示浏览器框架内各个控件的矩形区域"""

    def __init__(self, left, top, right, bottom):
        """
        创建矩形区域

        Parameters:
            left, top: 矩形左上角的x与y坐标
            right, bottom: 矩形右下角的x与y坐标
        """

        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom

    def contains_point(self, x, y):
        """判断坐标(x, y)是否落于当前Rect内"""
        return x >= self.left and x < self.right and y >= self.top and y < self.bottom
