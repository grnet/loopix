import datetime
from Queue import PriorityQueue, Queue, Empty
from core import LoopixClient, LoopixMixNode, LoopixProvider
import supportFunctions as sf
import time
import json

with open('config.json') as infile:
    _PARAMS = json.load(infile)

def schedule(delay):
    return datetime.datetime.now() + datetime.timedelta(delay)


def enqueue(queue, delay, data):
    fire_time = schedule(delay)
    print "ENQUEUE %s" % (fire_time)
    queue.put((fire_time, data))


def process_queue(event_queue, inboxes):
    pqueue = PriorityQueue()
    timeout = 0
    while True:
        try:
            element = event_queue.get(block=True, timeout=timeout)
            handle_element(pqueue, element, inboxes)
        except Empty:
            pass
        while True:
            try:
                elem = pqueue.get(block=False)
            except Empty:
                break
            delta_secs = handle_element(pqueue, elem, inboxes)
            if delta_secs > 0:
                timeout = delta_secs
                break


def handle_element(pqueue, element, inboxes):
    (fire_time, data) = element
    message, addr = data
    now = datetime.datetime.now()
    delta = fire_time - now
    delta_secs = delta.total_seconds()
    if delta_secs <= 0:
        print "SENDING %s to %s" % (now, addr)
        inboxes[addr].put(message)
    else:
        pqueue.put(element)
    return delta_secs


class MixNodeHandler(object):
    EXP_PARAMS_LOOPS = (float(_PARAMS["parametersMixnodes"]["EXP_PARAMS_LOOPS"]), None)

    def __init__(self, mixnode):
        self.mixnode = mixnode
        self.queue = Queue()

    def register_providers(self, providers):
        self.mixnode.providers = providers

    def register_mixnodes(self, mixnodes):
        self.mixnode.mixnodes = mixnodes

    def process_inbox(self, inbox):
        while True:
            message = inbox.get()
            self.process_message(message)

    def process_message(self, message):
        flag, data = self.mixnode.process_message(message)
        if flag == "RELAY":
            delay, new_message, new_addr = data
            enqueue(self.queue, delay, (new_message, new_addr))

    def send_loop_messages(self):
        while True:
            interval = sf.sampleFromExponential(self.EXP_PARAMS_LOOPS)
            time.sleep(interval)
            message, new_addr = self.mixnode.create_loop_message()
            enqueue(self.queue, 0, (message, new_addr))


class ProviderHandler(MixNodeHandler):
    def __init__(self, provider):
        MixNodeHandler.__init__(self, provider)
        self.provider = provider
        self.storage = {}

    def register_clients(self, clients):
        self.provider.clients = clients

    def process_real_message(self, message):
        flag, data = self.provider.process_message(message)
        if flag == "RELAY":
            delay, new_message, new_addr = data
            enqueue(self.queue, delay, (new_message, new_addr))
        elif flag == "STORE":
            new_message, next_name = data
            recipient = self.provider.clients[next_name]
            new_addr = recipient.host, recipient.port
            self.saveInStorage(next_name, (new_message, new_addr))

    def saveInStorage(self, key, value):
        if key in self.storage:
            self.storage[key].append(value)
        else:
            self.storage[key] = [value]

    def process_message(self, data):
        if data[:8] == "PULL_MSG":
            data = self.provider.get_user_messages(data[8:])
            enqueue(self.queue, 0, data)
        else:
            self.process_real_message(data)


class ClientHandler(object):

    EXP_PARAMS_PAYLOAD = (
        float(_PARAMS["parametersClients"]["EXP_PARAMS_PAYLOAD"]), None)

    EXP_PARAMS_LOOPS = (
        float(_PARAMS["parametersClients"]["EXP_PARAMS_LOOPS"]), None)
    EXP_PARAMS_COVER = (
        float(_PARAMS["parametersClients"]["EXP_PARAMS_COVER"]), None)

    def __init__(self, client):
        self.client = client
        self.queue = Queue()
        self.buffer_queue = Queue()

    def register_providers(self, providers):
        self.client.providers = providers

    def register_mixnodes(self, mixnodes):
        self.client.mixnodes = mixnodes

    def register_known_clients(self, known_clients):
        self.client.known_clients = known_clients

    def read_mail(self, inbox):
        while True:
            message = inbox.get()
            processed = self.process_message(message)
            print "User %s: READ MAIL" % self.client.name

    def process_message(self, message):
        return self.client.process_message(message)

    def make_loop_stream(self):
        while True:
            interval = sf.sampleFromExponential(self.EXP_PARAMS_LOOPS)
            time.sleep(interval)
            loop_message, next_addr = self.client.create_loop_message()
            enqueue(self.queue, 0, (loop_message, next_addr))

    def make_drop_stream(self):
        while True:
            interval = sf.sampleFromExponential(self.EXP_PARAMS_COVER)
            time.sleep(interval)
            random_client = self.client.selectRandomClient()
            drop_message, next_addr = self.client.create_drop_message(random_client)
            enqueue(self.queue, 0, (drop_message, next_addr))

    def make_pull_request_stream(self):
        while True:
            interval = 10
            time.sleep(interval)
            pull_message, next_addr = "PULL", (self.client.provider.host, self.client.provider.port)
            enqueue(self.queue, 0, (pull_message, next_addr))

    def next_message(self):
        if not self.buffer_queue.empty():
            return self.buffer_queue.get()
        else:
            random_client = self.client.selectRandomClient()
            return self.client.create_drop_message(random_client)

    def make_actual_message_stream(self):
        while True:
            interval = sf.sampleFromExponential(self.EXP_PARAMS_PAYLOAD)
            time.sleep(interval)
            data = self.next_message()
            enqueue(self.queue, 0, data)

    def prepare_actual_message(self, message, receiver):
        data = self.client.create_actual_message(message, receiver)
        self.client.buffer_queue.put(data)



# client_handler = client_handlers[0]
# #client_handler.make_loop_stream()
# #client_handler.make_drop_stream()
# #client_handler.make_actual_message_stream()
# client_handler.make_pull_request_stream()
