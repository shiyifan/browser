from font import get_font
from rect import Rect
from commands import DrawOutline, DrawText


# 浏览器的tab标签、地址栏以及按钮等部分
# "browser chrome"这个短语最初指浏览器的框架部分（地址栏、按钮、菜单栏等）
class Chrome:
    def __init__(self, browser):
        self.browser = browser
        self.font = get_font(20, "normal", "roman")  # 用于各个控件的字体
        self.font_height = self.font.metrics("linespace")

        self.padding = 5
        self.tabbar_top = 0  # tab标签条的顶部y坐标
        self.tabbar_bottom = self.font_height + 2 * self.padding  # tab标签条的底部y坐标

        # 新建tab页的按钮"+"
        plus_width = self.font.measure("+") + 2 * self.padding  # 新建tab页的"+"按钮宽度
        self.newtab_rect = Rect(
            self.padding,
            self.padding,
            self.padding + plus_width,
            self.padding + self.font_height,
        )

    # 计算"self.tabs"中，第i个tab标签的矩形绘制区域
    def tab_rect(self, i):
        # "+"按钮的右侧x坐标，作为绘制tab标签的起点
        tabs_start = self.newtab_rect.right + self.padding

        tab_width = self.font.measure("Tab X") + 2 * self.padding
        return Rect(
            tabs_start + tab_width * i,
            self.tabbar_top,
            tabs_start + tab_width * (i + 1),
            self.tabbar_bottom,
        )

    def paint(self):
        cmds = []

        # 绘制"+"按钮
        cmds.append(DrawOutline(self.newtab_rect, "black", 1))
        cmds.append(
            DrawText(
                self.newtab_rect.left + self.padding,
                self.newtab_rect.top,
                "+",
                self.font,
                "black",
            )
        )

        for i, tab in enumerate(self.browser.tags):
            bounds = self.tab_rect(i)
            cmds.append()

        return cmds
