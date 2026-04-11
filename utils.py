"""Some Utils functions"""


# 树状结构转为扁平的list结构
def tree_to_list(tree, list):
    list.append(tree)
    for child in tree.children:
        tree_to_list(child, list)
    return list


def print_err(msg):
    print(f"\033[31m{msg}\033[0m")


def print_warn(msg):
    print(f"\033[33m{msg}\033[0m")
