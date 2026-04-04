from font import get_font
from rect import Rect
from commands import DrawOutline, DrawText, DrawLine, DrawRect
import const
from url import URL


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

        self.bottom = self.tabbar_bottom

    def tab_rect(self, i):
        """计算"self.tabs"中，第i个tab标签的矩形绘制区域"""

        # "+"按钮的右侧x坐标，作为绘制tab标签的起点
        tabs_start = self.newtab_rect.right + self.padding

        tab_width = self.font.measure("Tab X") + 2 * self.padding
        return Rect(
            tabs_start + tab_width * i,
            self.tabbar_top,
            tabs_start + tab_width * (i + 1),
            self.tabbar_bottom,
        )

    def click(self, x, y):
        if self.newtab_rect.contains_point(x, y):
            # 当点击在"+"按钮时
            self.browser.new_tab(URL(const.HTTP_URL))
        else:
            # 当点击在tab标签时
            for i, tab in enumerate(self.browser.tabs):
                if self.tab_rect(i).contains_point(x, y):
                    self.browser.active_tab = tab
                    break

    def paint(self):
        cmds = []

        # 绘制背景以凸显按钮、tab标签之类的内容
        cmds.append(DrawRect(Rect(0, 0, const.WIDTH, self.bottom), "white"))
        # chrome的底部边缘可能与当前tab的底部边缘冲突
        cmds.append(DrawLine(0, self.bottom, const.WIDTH, self.bottom, "black", 1))

        # 绘制"+"按钮与按钮边框
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

        # 绘制tab标签。
        for i, tab in enumerate(self.browser.tabs):
            bounds = self.tab_rect(i)  # 计算每个tab标签绘制的矩形区域

            # 不绘制完整的矩形轮廓，仅根据"tab_rect"计算得到的矩形区域绘制矩形的左侧垂直边以及tab标签文字
            cmds.append(
                DrawLine(bounds.left, 0, bounds.left, bounds.bottom, "black", 1)
            )
            cmds.append(
                DrawLine(bounds.right, 0, bounds.right, bounds.bottom, "black", 1)
            )
            cmds.append(
                DrawText(
                    bounds.left + self.padding,
                    bounds.top + self.padding,
                    "TAB {}".format(i),
                    self.font,
                    "black",
                )
            )

            # 突出当前的正在显示的tab
            if tab == self.browser.active_tab:
                # 下面这两条线可能与chrome的底部边缘线条冲突,所以宽度改成2
                cmds.append(
                    DrawLine(0, bounds.bottom, bounds.left, bounds.bottom, "blue", 2)
                )
                cmds.append(
                    DrawLine(
                        bounds.right,
                        bounds.bottom,
                        const.WIDTH,
                        bounds.bottom,
                        "blue",
                        2,
                    )
                )

        return cmds
