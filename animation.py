# 计算CSS中，数值类型属性的animation的每一帧的值
class NumericAnimation:
    def __init__(self, old_value, new_value, num_frames):
        self.old_value = old_value
        self.new_value = new_value
        self.num_frames = num_frames  # 从old_value过渡至new_value一共需要的帧数

        self.frame_count = 1
        total_change = self.new_value - self.old_value
        self.change_per_frame = total_change / num_frames  # 每一帧的变化值

    # 计算并返回每一帧的值
    def animate(self):
        self.frame_count += 1
        if self.frame_count > self.num_frames:
            return

        current_value = self.old_value + self.frame_count * self.change_per_frame

        return str(current_value)
