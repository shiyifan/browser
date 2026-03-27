class CSSParser:
    def __init__(self, s):
        self.s = s
        self.i = 0
    
    def whitespace(self):
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1
    
    # 截取css属性名称、属性值（数字、百分比、颜色等），并返回截取后的值
    def word(self):
        start = self.i
        while self.i < len(self.s):
            if self.s[self.i].isalnum() or self.s[self.i] in "#-.%":
                # 假设css属性名与属性值仅由字母、数字以及"#-.%"特殊字符构成
                self.i += 1 # 继续读取下个字符
            else:
                break
        if not (self.i > start):
            raise Exception(f"Parsing Error, start: {start}, self.i: {self.i}")
        return self.s[start:self.i] # 返回截取得到的值

    def literal(self, literal):
        if not (self.i < len(self.s) and self.s[self.i] == literal):
            raise Exception(f"Parsing Error, literal expected: {literal}, actual: {self.s[self.i]}")
        self.i += 1