from tags import Text
from utils import is_focusable


# a11y(accessibility) tree结构中的结点
class AccessibilityNode:
    def __init__(self, node):
        self.node = node
        self.children = []
        self.text = ""

        if isinstance(node, Text):
            if is_focusable(node.parent):
                self.role = "focusable text"
            else:
                self.role = "StaticText"
        else:
            if "role" in node.attributes:
                self.role = node.attributes["role"]
            elif node.tag == "a":
                self.role = "link"
            elif node.tag == "input":
                self.role = "textbox"
            elif node.tag == "button":
                self.role = "button"
            elif node.tag == "html":
                self.role = "document"
            elif is_focusable(node):
                self.role = "focusable"
            else:
                self.role = "none"

    # 构建当前DOM结点"self.node"的Accessibility Tree
    def build(self):
        for child_node in self.node.children:
            self.build_internal(child_node)

        match self.role:
            case "StaticText":
                self.text = repr(self.node.text)
            case "focusable text":
                self.text = f"Focusable text: {self.node.text}"
            case "focusable":
                self.text = "Focusable element"
            case "textbox":
                if "value" in self.node.attributes:
                    value = self.node.attributes["value"]
                elif (
                    self.node.tag != "input"
                    and self.node.children
                    and isinstance(self.node.children[0], Text)
                ):
                    value = self.node.children[0].text
                else:
                    value = ""
                self.text = f"Input box: {value}"
            case "button":
                self.text = "Button"
            case "link":
                self.text = "Link"
            case "alert":
                self.text = "Alert"
            case "document":
                self.text = "Document"

        if self.node.is_focused:
            self.text = f"{self.text} is focused"

        # if self.role == "StaticText":
        #     self.text = repr(self.node.text)
        # elif self.role == "focusable text":
        #     self.text = f"Focusable text: {self.node.text}"
        # elif self.role == "focusable":

    # 根据DOM结点下的DOM Tree结构构建a11y tree. 对于非a11y的DOM结点将不创建对应的a11y tree node.
    # 如下图所示：
    #
    #        DOM Tree                                    Accessibility Tree
    #
    #    html (role=document)                              document
    #     |                                                  |
    #     +->div 1                                           +->textbox  2
    #     |   |                                              |
    #     |   +-->input  (role=textbox) 2                    +->button   3
    #     |   |                                              |
    #     |   +-->button (role=button)  3     ------>        |
    #     |                                                  +->focusable(div tabindex=1)  4
    #     |                                                        |
    #     +->div [tabindex=1]  4                                   +->link      5
    #         |                                                    |
    #         +-->a     (role=link)      5                         +->textbox   6
    #         |
    #         +-->input (role=textbox)   6
    #
    def build_internal(self, child_node):
        child = AccessibilityNode(child_node)
        if child.role != "none":
            self.children.append(child)
            child.build()
        else:
            # child不是a11y的结点,不创建这个node而继续检查这个child下一级的children,
            # 下一级的children中如果有a11y的结点则添加至当前a11y node的children中，而非child的children中
            for grandchild_node in child_node.children:
                self.build_internal(grandchild_node)

    def __repr__(self):
        return f"role={self.role}, text={self.text}"
