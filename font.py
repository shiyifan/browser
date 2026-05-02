from skia import *

# 字体缓存
FONTS = {}


# 从"FONTS"缓存中获取字体
def get_font(size, weight, style):
    key = (weight, style)

    if key not in FONTS:
        if weight == "bold":
            skia_weight = FontStyle.kBold_Weight
        else:
            skia_weight = FontStyle.kNormal_Weight
        if style == "italic":
            skia_style = FontStyle.kItalic_Slant
        else:
            skia_style = FontStyle.kUpright_Slant
        skia_width = FontStyle.kNormal_Width
        style_info = FontStyle(skia_weight, skia_width, skia_style)
        font = Typeface("Arial", style_info)
        FONTS[key] = font

    return Font(FONTS[key], size)

def linespace(font):
    """计算skia Font的\"linespace\""""

    return font.getMetrics().fDescent - font.getMetrics().fAscent
