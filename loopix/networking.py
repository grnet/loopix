import datetime
from Queue import PriorityQueue, Queue
from core import LoopixClient, LoopixMixNode, LoopixProvider, generate_all
import supportFunctions as sf
import time

def schedule(delay):
    return datetime.datetime.now() + datetime.timedelta(delay)


def enqueue(pqueue, delay, data):
    fire_time = schedule(delay)
    print "ENQUEUE %s %s" % (fire_time, data)
    pqueue.put((fire_time, data))


def process_queue(pqueue, event_handler):
    while True:
        element = event_handler.wait()
        handle_element(pqueue, element)
        while True:
            if pqueue.empty():
                break
            elem = pqueue.get()
            if not handle_element(pqueue, elem):
                break


def handle_element(pqueue, element):
    (fire_time, data) = element
    now = datetime.datetime.now()
    if fire_time <= now:
        print "SENDING %s to %s" % (now, data[1])
        return True
    else:
        pqueue.put(elem)
        return False


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

    def process_message(self, message):
        flag, data = self.provider.process_message(message)
        if flag == "RELAY":
            delay, new_message, new_addr = data
            enqueue(self.priority_queue, delay, (new_message, new_addr))
        elif flag == "STORE":
            new_message, next_name = data
            recipient = self.provider.clients[name]
            new_addr = recipient.host, recipient.port
            self.provider.saveInStorage(name, (new_message, new_addr))

    def handle_package(self, data):
        if data[:8] == "PULL_MSG":
            data = self.provider.get_user_messages(data[8:])
            enqueue(self.priority_queue, 0, data)
        else:
            self.process_message(data)


class ClientHandler(object):
    def __init__(self, client):
        self.client = client
        self.priority_queue = PriorityQueue()
        self.buffer_queue = Queue()
        self.inbox = Queue()

    def read_mail(self):
        while not self.inbox.empty():
            message = self.inbox.pop()
            processed = self.process_message(message)
            print processed

    def process_message(self, message):
        return self.client.process_message(message)

    def make_loop_stream(self):
        while True:
            interval = sf.sampleFromExponential(self.client.EXP_PARAMS_LOOPS)
            time.sleep(interval)
            loop_message, next_addr = self.client.create_loop_message()
            enqueue(self.priority_queue, 0, (loop_message, next_addr))

    def make_drop_stream(self):
        while True:
            interval = sf.sampleFromExponential(self.client.EXP_PARAMS_COVER)
            time.sleep(interval)
            random_client = self.client.selectRandomClient()
            drop_message, next_addr = self.client.create_drop_message(random_client)
            enqueue(self.priority_queue, 0, (drop_message, next_addr))

    def make_pull_request_stream(self):
        while True:
            interval = 10
            time.sleep(interval)
            pull_message, next_addr = "PULL", (self.client.provider.host, self.client.provider.port)
            enqueue(self.priority_queue, 0, (pull_message, next_addr))

    def next_message(self):
        if not self.buffer.empty():
            return self.buffer.get()
        else:
            random_client = self.client.selectRandomClient()
            return self.client.create_drop_message(random_client)

    def make_actual_message_stream(self):
        while True:
            interval = sf.sampleFromExponential(self.client.EXP_PARAMS_PAYLOAD)
            time.sleep(interval)
            data = self.client.next_message()
            enqueue(self.priority_queue, 0, data)

    def prepare_actual_message(self, message, receiver):
        data = self.client.create_actual_message(message, receiver)
        self.client.buffer.put(data)


env = generate_all()
client_core = env.client_objects['User0']

client_hanlder = ClientHandler(client_core)

