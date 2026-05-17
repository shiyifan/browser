from threading import Timer

class Watchdog:
    def __init__(self, timeout):
        self.timeout = timeout
        self.timer = self.new_timer(self.timeout)

    def feed(self):
        self.timer.cancel()
        self.timer = self.new_timer(self.timeout)
    
    def new_timer(self, timeout):
        def bark():
            raise Exception("WOOF! WOOF!")

        t = Timer(timeout, bark)
        t.name = "watch_dog"
        t.start()

        return t
