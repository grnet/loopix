import datetime
from Queue import PriorityQueue
from core import LoopixClient, LoopixMixNode, LoopixProvider, generate_all
import supportFunctions as sf
import time

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


class ClientHandler(object):
    def __init__(self, client):
        self.client = client
        self.priority_queue = PriorityQueue()


    def process_message(self, message):
        received_message = self.client.process_message(message)

    def send_loop_message(self):
        while True:
            interval = sf.sampleFromExponential(self.client.EXP_PARAMS_LOOPS)
            time.sleep(interval)
            loop_message, next_addr = self.client.create_loop_message()
            enqueue(self.priority_queue, 0, (loop_message, next_addr))


    def send_drop_message(self):
        while True:
            interval = sf.sampleFromExponential(self.client.EXP_PARAMS_COVER)
            time.sleep(interval)
            random_client = self.client.selectRandomClient()
            drop_message, next_addr = self.client.create_drop_message(random_client)
            enqueue(self.priority_queue, 0, (drop_message, next_addr))


    def send_pull_request(self):
        while True:
            interval = 10
            time.sleep(interval)
            pull_message, next_addr = "PULL", (self.client.provider.host, self.client.provider.port)
            enqueue(self.priority_queue, 0, (pull_message, next_addr))

    def send_real_message(self):
        while True:
            interval = sf.sampleFromExponential(self.client.EXP_PARAMS_PAYLOAD)
            time.sleep(interval)
            self.client.next_message()




env = generate_all()
client_core = env.client_objects['User0']

client_hanlder = ClientHandler(client_core)

