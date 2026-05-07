"""Some Utils functions"""

from skia import Color, ColorBLACK
from const import NAMED_COLORS


# 树状结构转为扁平的list结构
def tree_to_list(tree, list):
    list.append(tree)
    for child in tree.children:
        tree_to_list(child, list)
    return list


def parse_color(color):
    """解析16进制或者关键字的颜色数值为Skia的Color"""

    if color.startswith("#") and len(color) == 7:
        # 无alpha通道的Hex颜色值

        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        return Color(r, g, b)
    
    elif color.startswith("#") and len(color) == 9:
        # 带有alpha通道的Hex颜色值

        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        a = int(color[7:9], 16)
        return Color(r, g, b, a)

    elif color in NAMED_COLORS:
        return parse_color(NAMED_COLORS[color])

    else:
        return ColorBLACK


class Log:
    def i(self, *msg):
        print(f"\033[32m", end="")
        print(*msg, end="")
        print("\033[0m")

    def w(self, *msg):
        print(f"\033[33m", end="")
        print(*msg, end="")
        print("\033[0m")

    def e(self, *msg):
        print(f"\033[31m", end="")
        print(*msg, end="")
        print("\033[0m")

    def js(self, *msg):
        print(f"\033[34m", end="")
        print(*msg, end="")
        print("\033[0m")


log = Log()
