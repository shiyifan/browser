# canvas的大小
WIDTH, HEIGHT = 1024, 768
# 在canvas上绘制文字时的间距与行距
HSTEP, VSTEP = 13, 18
# 滚动步长
SCROLL_STEP = 20

HTTP_URL = "http://localhost:3000"
# HTTP_URL = "https://www.baidu.com"
# HTTP_URL = "https://browser.engineering/index.html"

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
