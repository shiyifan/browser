from css_selectors import TagSelector, DescendantSelector


# html element "style"属性值解析与".css"文件解析
# 注意HTML标签的*属性值中不可以包含空格*，因为"HTMLParser"根据空格分词
# 但是".css"文件中可以包含空格
class CSSParser:
    def __init__(self, s):
        self.s = s  # css字符串
        self.i = 0  # css字符串中，当前正在解析的位置

    # 跳过当前位置的连续空白字符
    def whitespace(self):
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    # 截取css属性名称、属性值（数字、百分比、颜色等），并返回截取后的值
    def word(self):
        start = self.i
        while self.i < len(self.s):
            if self.s[self.i].isalnum() or self.s[self.i] in "#-.%":
                # 假设css属性名与属性值仅由字母、数字以及"#-.%"特殊字符构成
                self.i += 1  # 继续读取下个字符
            else:
                break
        if not (self.i > start):
            # 未能截取到任何有效的字符
            raise Exception(f"Parsing Error, start: {start}, self.i: {self.i}")
        return self.s[start : self.i]  # 返回截取得到的值

    # 跳过当前位置的某个字符(literal)，如果该literal与css中被跳过的字符不相同则抛出异常
    def literal(self, literal):
        if not (self.i < len(self.s) and self.s[self.i] == literal):
            raise Exception(
                f"Parsing Error, literal expected: {literal}, actual: {self.s}[{self.i}]"
            )
        self.i += 1

    # 从当前位置向后解析，截取一个css属性名与属性值
    def pair(self):
        prop = self.word()  # 截取属性名
        self.whitespace()
        self.literal(":")
        self.whitespace()
        val = self.word()  # 截取属性值
        return prop.casefold(), val

    def body(self):
        pairs = {}
        # 解析css selector后花括号里面的具体rule，直到"}"字符
        while self.i < len(self.s) and self.s[self.i] != "}":
            try:
                prop, val = self.pair()
                pairs[prop] = val
                self.whitespace()
                self.literal(";")
                self.whitespace()
            except Exception as e:
                # 如果解析rule时发生异常，那么忽略后续字符直到";"或者"}"
                why = self.ignore_until([";", "}"])
                if why == ";":
                    self.literal(";")
                    self.whitespace()
                else:
                    break
        return pairs

    def ignore_until(self, chars):
        while self.i < len(self.s):
            if self.s[self.i] in chars:
                return self.s[self.i]
            else:
                self.i += 1
        return None

    # 截取selector
    #
    # 对于多个tag selector构成的DescendantSelector，最终的selector对象将是这样的嵌套结构
    #
    # selector: div header span
    #
    #
    #                 DescendantSelector
    # +---------------------------------------------------+
    # |                                                   |
    # |         DescendantSelector                        |
    # |   +----------------------------+                  |
    # |   |     div          header    |       span       |
    # |   | (ancestor)    (descendant) |                  |
    # |   +----------------------------+                  |
    # |             (ancestor)             (descendant)   |
    # |                                                   |
    # +---------------------------------------------------+
    def selector(self):
        out = TagSelector(self.word().casefold())
        self.whitespace()
        while self.i < len(self.s) and self.s[self.i] != "{":
            # tag selector之后还有其他selector,说明这是一个descendant selector，继续解析
            tag = self.word()
            descendant = TagSelector(tag.casefold())
            out = DescendantSelector(out, descendant)  # 创建嵌套式的DescendantSelector
            self.whitespace()
        return out

    def parse(self):
        rules = []
        while self.i < len(self.s):
            try:
                self.whitespace()
                selector = self.selector()
                self.literal("{")
                self.whitespace()
                body = self.body()  # body中的异常已在函数内捕获并处理
                self.literal("}")
                rules.append((selector, body))
            except Exception as e:
                # 解析selector时发生异常，忽略后续字符直到"}"
                why = self.ignore_until(["}"])
                if why == "}":
                    self.literal("}")
                    self.whitespace()
                else:
                    break
        return rules
