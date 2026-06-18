class CommitData:
    """保存tab计算布局之后，通知browser进行raster的所需信息"""

    def __init__(self, url, scroll, height, display_list, composited_updates, accessibility_tree):
        self.url = url
        self.scroll = scroll
        self.height = height
        self.display_list = display_list
        self.composited_updates = composited_updates
        self.accessibility_tree = accessibility_tree
