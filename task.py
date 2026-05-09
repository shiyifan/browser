class Task:
    def __init__(self, task_code, *args):
        self.task_code = task_code
        self.args = args

    def run(self):
        self.task_code(*self.args)
        self.task_code = None
        self.args = None


class TaskRunner:
    def __init__(self, tab):
        self.tab = tab
        self.tasks = []  # FIFO队列，保存任务

    def schedule_task(self, task):
        self.tasks.append(task)

    def run(self):
        if len(self.tasks) > 0:
            task = self.tasks.pop(0)  # 取出队列第一个task
            task.run()
