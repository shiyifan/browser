# 目前仅支持tag selector以及由tag selector构成的descendant selector
# 例如："span", "div span", "div header p"
from tags import Element

class TagSelector:
    def __init__(self, tag):
        self.tag = tag

    def matches(self, node):
        return isinstance(node, Element) and self.tag == node.tag


class DescendantSelector:
    def __init__(self, ancestor, descendant):
        self.ancestor = ancestor
        self.descendant = descendant

    def matched(self, node):
        # 先判断DOM结点是否匹配低位的selector，如果低位的selector匹配失败，那么无需继续匹配高位selector
        if not self.descendant.matches(node):
            return False

        # 如果低位匹配成功，那么继续匹配高位selector
        # 检查DOM结点的所有父结点中，是否存在一个父结点满足高位selector
        while node.parent:
            if self.ancestor.matches(node.parent):
                return True
            node = node.parent  # 继续向上访问父结点

        return False  # 没有DOM父结点满足高位selector,匹配失败
