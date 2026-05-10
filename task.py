from threading import Condition


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

        self.condition = Condition()  # task queue的添加task与取出task时的同步锁

    def schedule_task(self, task):
        self.condition.acquire(blocking=True)
        self.tasks.append(task)
        self.condition.notify_all()
        self.condition.release()

    def run(self):
        task = None

        self.condition.acquire(blocking=True)
        if len(self.tasks) > 0:
            task = self.tasks.pop(0)  # 取出队列第一个task
        self.condition.release()

        if task:
            task.run()
