from threading import Timer

class Watchdog:
    def __init__(self, timeout):
        self.timeout = timeout
        self.timer = self.new_timer(self.timeout)

    def feed(self):
        self.timer.cancel()
        self.timer = self.new_timer(self.timeout)
    
    def dismiss(self):
        self.timer.cancel()
    
    def new_timer(self, timeout):
        def bark():
            # 如果在timeout时间内没有调用"feed()",则抛出异常
            raise Exception("WOOF! WOOF!")

        t = Timer(timeout, bark)
        t.name = "watch_dog"
        t.start()

        return t
