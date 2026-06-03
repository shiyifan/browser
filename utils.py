"""Some Utils functions"""

from skia import Color, ColorBLACK, Matrix, Rect
import const


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

    elif color in const.NAMED_COLORS:
        return parse_color(const.NAMED_COLORS[color])

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


# 输出DOM Tree结构
def print_tree(node, indent=0):
    print(" " * indent, node)

    if not hasattr(node, "children"):
        return
    for child in node.children:
        print_tree(child, indent + 2)


# 解析css"transform"语法，目前仅支持解析"translate()"
def parse_transform(transform_str):
    if transform_str.find("translate(") < 0:
        return None
    left_paren = transform_str.find("(")
    right_paren = transform_str.find(")")
    x_px, y_px = transform_str[left_paren + 1 : right_paren].split(",")

    return (float(x_px[:-2]), float(y_px[:-2]))


# 按'display_item'在display list树状结构中的位置，依次向上遍历各parent的css"translation"效果,
# 计算出'rect'相对于"窗口可视区域"的实际绘制矩形区域.
# 如果计算之后的实际绘制矩形超出窗口的可视区域，还需要去掉超出范围的区域,仅保留两个区域的交集
def local_to_absolute(display_item, rect):
    # 计算窗口的可视区域
    vp_width = const.WIDTH - 2 * const.HSTEP
    vp_height = const.HEIGHT - 2 * const.VSTEP
    vp_rect = Rect.MakeXYWH(const.HSTEP, const.VSTEP, vp_width, vp_height)

    while display_item.parent:
        rect = display_item.parent.map(rect)
        display_item = display_item.parent

    return reasonable_intersect(vp_rect, rect)


def absolute_to_local(display_item, rect):
    parent_chain = []
    while display_item.parent:
        parent_chain.append(display_item.parent)
        display_item = display_item.parent
    for parent in reversed(parent_chain):
        rect = parent.unmap(rect)
    return rect


# 将矩形区域按照既定的"translation"返回转换后的矩形区域
def map_translation(rect, translation, reversed=False):
    if not translation:
        return rect
    else:
        x, y = translation
        matrix = Matrix()
        if reversed:
            matrix.setTranslate(-x, -y)
        else:
            matrix.setTranslate(x, y)
        return matrix.mapRect(rect)


def reasonable_intersect(r0, r1):
    """计算两个矩形的交集矩形区域，当且仅当两个矩形完全不相交时才返回'None',
    对于只有'边相邻'的情况将返回宽度或者高度为0的矩形"""

    # 计算两个矩形中，最大的左上角坐标与最小的右下角坐标
    left = max(r0.left(), r1.left())
    top = max(r0.top(), r1.top())
    right = min(r0.right(), r1.right())
    bottom = min(r0.bottom(), r1.bottom())

    if left > right or top > bottom:
        # 两个矩形区域完全不相交，边也不相邻

        return None

    return Rect.MakeLTRB(left, top, right, bottom)
