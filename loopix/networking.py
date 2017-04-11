import datetime
from Queue import PriorityQueue

def schedule(delay):
    return datetime.datetime.now() + datetime.timedelta(delay)


def enqueue(pqueue, delay, data):
    fire_time = schedule(delay)
    print "ENQUEUE %s %s" % (fire_time, data)
    pqueue.put((fire_time, data))


class MixNodeHandler(object):
    def __init__(self, mixnode):
        self.mixnode = mixnode
        self.priority_queue = PriorityQueue()

    def process_message(self, message):
        flag, data = self.mixnode.process_message(message)
        if flag == "RELAY":
            delay, new_message, new_addr = data
            enqueue(self.priority_queue, delay, (new_message, new_addr))

    def send_loop_messages(self):
        while True:
            interval = sf.sampleFromExponential(self.mixnode.EXP_PARAMS_LOOPS)
            time.sleep(interval)
            enqueue(self.priority_queue, 0, (message, new_addr))


class ProviderHandler(MixNodeHandler):
    def __init__(self, provider):
        MixNodeHandler.__init__(self, provider)
        self.provider = provider

    def handle_package(self, data):
        if data[:8] == "PULL_MSG":
            return self.provider.get_user_messages(data[8:])
        return self.provider.process_message(data)
