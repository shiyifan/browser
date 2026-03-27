# 绘制命令
# 将display list中各个绘制信息转换为绘制命令


class DrawText:
    # (x1, y1)为相对于canvas的坐标
    def __init__(self, x1, y1, text, font):
        self.left = x1
        self.top = y1
        self.text = text
        self.font = font

        # 表示当前行的底部纵坐标，用于判断绘制位置是否位于canvas的可见区域外
        self.bottom = y1 + font.metrics("linespace")

    # scroll: 已向上滚动的距离
    def execute(self, scroll, canvas):
        canvas.create_text(
            self.left, self.top - scroll, text=self.text, font=self.font, anchor="nw"
        )


class DrawRect:
    # (x1, y1), (x2, y2)为相对于canvas的坐标
    def __init__(self, x1, y1, x2, y2, color):
        self.top = y1
        self.left = x1
        self.bottom = y2
        self.right = x2
        self.color = color

    # scroll: 已向上滚动的距离
    def execute(self, scroll, canvas):
        canvas.create_rectangle(
            self.left,
            self.top - scroll,
            self.right,
            self.bottom - scroll,
            width=0,  # no default border
            fill=self.color,
        )
