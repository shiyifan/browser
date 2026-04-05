from tags import Text, Element
from const import *


class HTMLParser:
    def __init__(self, body):
        self.body = body
        self.unfinished = []

    # 解析HTML代码中标签与纯文本，并返回由"Text"与"Element"构成的DOM树
    def parse(self):
        text = ""
        in_tag = False

        for c in self.body:
            if c == "<":
                in_tag = True
                if text:
                    # 提取标签之前（"<"字符之前）的纯文本
                    self.add_text(text)
                text = ""
            elif c == ">":
                # 读取标签结束字符">",并提取标签
                in_tag = False
                self.add_tag(text)
                text = ""
            else:
                text += c

        if not in_tag and text:
            self.add_text(text)

        return self.finish()  # 返回DOM结构

    # 在DOM树中添加text节点
    def add_text(self, text):
        if text.isspace():
            # 忽略仅空白字符构成的text结点
            return
        self.implicit_tags(None)

        parent = self.unfinished[-1]
        node = Text(text, parent)
        parent.children.append(node)

    # 在DOM树中添加tag结点
    def add_tag(self, tag):
        if tag.startswith("!"):
            # 忽略"<!doctype html>"
            return

        tag, attributes = self.get_attibutes(tag)  # 解析标签名与标签属性
        self.implicit_tags(tag)

        if tag.startswith("/"):
            # 如果是close label"</xxxx>"，
            # 表示unfinished中最后一个label已结束，并添加至父结点中

            if len(self.unfinished) == 1:
                # 如果仅剩余最顶级标签，该标签无parent，那么直接返回
                return
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)

        elif tag in SELF_CLOSING_TAGS:
            parent = self.unfinished[-1]
            parent.children.append(Element(tag, attributes, parent))

        else:
            # 如果是open label"<xxxx>"，
            # 新建一个label,其父结点是unfinished中最后一个label,并且将该label添加至unfinished中

            # 如果是第一个标签，那么该标签无parent
            parent = self.unfinished[-1] if self.unfinished else None

            node = Element(tag, attributes, parent)
            self.unfinished.append(node)

    def finish(self):
        if not self.unfinished:
            self.implicit_tags(None)

        while len(self.unfinished) > 1:
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
        return self.unfinished.pop()

    # 获取标签的"属性名=属性值"键值对
    # 注意属性值中不可以包含空格，因为通过空格分割每个键值对
    def get_attibutes(self, text):
        parts = text.split()
        tag = parts[0].casefold()
        attributes = {}

        # 解析标签的属性声明
        for attrpair in parts[1:]:
            if "=" in attrpair:
                # 形如"id=button"的属性声明
                key, value = attrpair.split("=", 1)
                # 如果属性值两侧有引号
                if len(value) > 2 and value[0] in ["'", '"']:
                    value = value[1:-1]

                attributes[key.casefold()] = value
            else:
                # 形如"disabled"、仅有属性名称的属性声明
                attributes[attrpair.casefold()] = ""

        return tag, attributes

    def implicit_tags(self, tag):
        while True:
            open_tags = [node.tag for node in self.unfinished]

            if open_tags == [] and tag != "html":
                # 如果第一个open的标签不是html，手动插入"<html>"
                self.add_tag("html")
            elif open_tags == ["html"] and tag not in ["head", "body", "/html"]:
                # 如果第二个open的标签不是<head>, <body>, </html>，那么
                # 也需要手动插入
                if tag in HEAD_TAGS:
                    self.add_tag("head")
                else:
                    self.add_tag("body")
            elif open_tags == ["html", "head"] and tag not in ["/head"] + HEAD_TAGS:
                self.add_tag("/head")
            else:
                break
