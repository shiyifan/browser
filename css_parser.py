# html element "style"属性解析
# 注意属性值中不可以包含空格，因为"HTMLParser"根据空格分词
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

    # 从当前位置向后解析，获取一个css属性名与属性值
    def pair(self):
        prop = self.word()
        self.whitespace()
        self.literal(":")
        self.whitespace()
        val = self.word()
        return prop.casefold(), val

    def body(self):
        pairs = {}
        while self.i < len(self.s):
            # try:
            prop, val = self.pair()
            pairs[prop] = val
            self.whitespace()
            self.literal(";")
            self.whitespace()
            # except Exception:
            #     why = self.ignore_until([";"])
            #     if why == ";":
            #         self.literal(";")
            #         self.whitespace()
            #     else:
            #         break;
        return pairs

    def ignore_until(self, chars):
        while self.i < len(self.s):
            if self.s[self.i] in chars:
                return self.s[self.i]
            else:
                self.i += 1
        return None
