# canvas的大小
WIDTH, HEIGHT = 1224, 868
# 在canvas上绘制文字时的间距与行距
HSTEP, VSTEP = 13, 18
# 滚动步长
SCROLL_STEP = 20

HTTP_URL = "https://localhost:3000/b"
# HTTP_URL = "https://browser.engineering/invalidation.html"
# HTTP_URL = "https://www.baidu.com"
# HTTP_URL = "https://browser.engineering/index.html"
# HTTP_URL = "https://localhost:8000"
# HTTP_URL = "https://browser.engineering/examples/example11-rounded-background.html"

# 无end close tag的标签
SELF_CLOSING_TAGS = [
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
]

# 允许在"<head>"内的标签
HEAD_TAGS = [
    "base",
    "basefont",
    "bgsound",
    "noscript",
    "link",
    "meta",
    "title",
    "style",
    "script",
]

BLOCK_ELEMENTS = [
    "html",
    "body",
    "article",
    "section",
    "nav",
    "aside",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hgroup",
    "header",
    "footer",
    "address",
    "p",
    "hr",
    "pre",
    "blockquote",
    "ol",
    "ul",
    "menu",
    "li",
    "dl",
    "dt",
    "dd",
    "figure",
    "figcaption",
    "main",
    "div",
    "table",
    "form",
    "fieldset",
    "legend",
    "details",
    "summary",
]

# css中inherited properties以及默认值
# （注意：inherited properties的默认值仅应用于DOM根结点）
INHERITED_PROPERTIES = {
    "font-size": "16px",
    "font-style": "normal",
    "font-weight": "normal",
    "color": "black",
}

NAMED_COLORS = {
    "black": "#000000",
    "white": "#ffffff",
    "red": "#ff0000",
    "gray": "#808080",
    "blue": "#0000FF",
    "lightblue": "#add8e6",
    "orange": "#ffa500",
}

REFRESH_RATE_SEC = 0.033

SCHEDULE_ANIMATION_TIMER_TID = 9999999

# 是否绘制composited layer的边界以便于调试
SHOW_COMPOSITED_LAYER_BORDERS = True

# <iframe>默认的尺寸
IFRAME_WIDTH_PX = 300
IFRAME_HEIGHT_PX = 150

NO_FOCUS = -1  # 用于标识点击之后没有找到可设置的焦点的情况
