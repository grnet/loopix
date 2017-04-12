import datetime
from Queue import PriorityQueue, Queue, Empty
from core import LoopixClient, LoopixMixNode, LoopixProvider
import supportFunctions as sf
import time
import json
import threading

MAX_RETRIEVE = 500

with open('config.json') as infile:
    _PARAMS = json.load(infile)


class ThreadSafeDict(object):
    def __init__(self, *args, **kwargs):
        self._DICT = {}
        self._LOCK = threading.Lock()

    def lock(self):
        class Lock(object):
            def __enter__(this):
                self._LOCK.acquire()
                return self._DICT

            def __exit__(this, exctype, value, traceback):
                self._LOCK.release()
                if value is not None:
                    return False  # re-raise
        return Lock()


def schedule(delay):
    return datetime.datetime.now() + datetime.timedelta(0, delay)


def enqueue(queue, delay, data):
    fire_time = schedule(delay)
    queue.put((fire_time, data))


def process_queue(handler, inboxes):
    event_queue = handler.queue
    name = handler.name
    pqueue = PriorityQueue()
    timeout = 0
    while True:
        try:
            element = event_queue.get(block=True, timeout=timeout)
            handle_element(pqueue, element, inboxes, name)
        except Empty:
            pass
        while True:
            try:
                elem = pqueue.get(block=False)
            except Empty:
                break
            delta_secs = handle_element(pqueue, elem, inboxes, name)
            if delta_secs > 0:
                timeout = delta_secs
                break


def handle_element(pqueue, element, inboxes, name):
    (fire_time, data) = element
    message, addr = data
    now = datetime.datetime.now()
    delta = fire_time - now
    delta_secs = delta.total_seconds()
    if delta_secs <= 0:
        print "SENDING from %s to %s" % (name, addr)
        with inboxes.lock() as d:
            d[tuple(addr)].put(message)
    else:
        pqueue.put(element)
    return delta_secs


class MixNodeHandler(object):
    EXP_PARAMS_LOOPS = (float(_PARAMS["parametersMixnodes"]["EXP_PARAMS_LOOPS"]), None)

    def __init__(self, mixnode):
        self.mixnode = mixnode
        self.queue = Queue()
        self.name = mixnode.name

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
        self.storage = ThreadSafeDict()
        self.name = provider.name

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
        elif flag == "DROP":
            print "[%s] > DROPED MESSAGE" % self.name

    def saveInStorage(self, key, value):
        with self.storage.lock() as storage:
            if key in storage:
                storage[key].append(value)
            else:
                storage[key] = [value]

    def get_user_messages(self, name):
        with self.storage.lock() as storage:
            if name in storage:
                messages = storage[name]
                popped, rest = messages[:MAX_RETRIEVE], messages[MAX_RETRIEVE:]
                storage[name] = rest
                return popped
            return []

    def process_message(self, data):
        if data.startswith("PULL"):
            message_list = self.get_user_messages(data[4:])
            for message in message_list:
                enqueue(self.queue, 0, message)
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
        self.name = client.name

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
            interval = 2
            time.sleep(interval)
            pull_message, next_addr = "PULL"+self.client.name, (self.client.provider.host, self.client.provider.port)
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
