from threading import Condition, Thread


# 表示一个可以被schedule的任务
class Task:
    def __init__(self, task_code, *args):
        self.task_code = task_code
        self.args = args

    def run(self):
        self.task_code(*self.args)
        self.task_code = None
        self.args = None


# 负责管理和执行task的任务队列(Queue)
#
# 每个tab页持有一个task runner.
# 浏览器将某些可推迟执行的操作添加至task runner中。例如在实现setTimeout时，在其他thread中sleep指定之间之后,
# 此时将callback添加至Queue中，等待主线程空闲时执行.
class TaskRunner:
    def __init__(self, tab):
        self.tab = tab
        self.tasks = []  # FIFO队列，保存任务

        self.condition = Condition()  # task queue的添加task与取出task时的同步锁

        # 负责event loop并执行"self.tasks"中的task
        self.main_thread = Thread(target=self.run, name="Main Thread")

        self.needs_quit = False

    def schedule_task(self, task):
        self.condition.acquire(blocking=True)
        self.tasks.append(task)
        self.condition.notify_all()
        self.condition.release()
    
    def set_needs_quit(self):
        self.condition.acquire(blocking=True)
        self.needs_quit = True
        self.condition.notify_all()
        self.condition.release()
    
    def clear_pending_tasks(self):
        self.condition.acquire(blocking=True)
        self.tasks.clear()
        self.condition.release()

    def run(self):
        """在event loop中执行task"""

        while True:
            self.condition.acquire(blocking=True)

            # 是否结束event loop
            if self.needs_quit:
                self.condition.release()
                return

            task = None
            if len(self.tasks) > 0:
                task = self.tasks.pop(0)  # 取出队列第一个task
            else:
                self.condition.wait() # 队列中没有task时

            self.condition.release()

            if task:
                task.run()
            

    
    def start_thread(self):
        self.main_thread.start()
