import tkinter.font

# 字体缓存
FONTS = {}

# 从"FONTS"缓存中获取字体
def get_font(size, weight, style):
    key = (size, weight, style)

    if key not in FONTS:
        font = tkinter.font.Font(family="Times", size=size, weight=weight, slant=style)
        label = tkinter.Label(font=font)
        FONTS[key] = (font, label)

    return FONTS[key][0]