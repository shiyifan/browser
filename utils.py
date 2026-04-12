"""Some Utils functions"""


# 树状结构转为扁平的list结构
def tree_to_list(tree, list):
    list.append(tree)
    for child in tree.children:
        tree_to_list(child, list)
    return list


class Log:
    def i(self, *msg):
        print(f"\033[32m", end="")
        print(*msg, end="")
        print("\033[0m")

    def w(self, *msg):
        print(f"\033[33m", end="")
        print(*msg, end="")
        print("\033[0m")

    def e(self, *msg):
        print(f"\033[31m", end="")
        print(*msg, end="")
        print("\033[0m")

    def js(self, *msg):
        print(f"\033[34m", end="")
        print(*msg, end="")
        print("\033[0m")


log = Log()
