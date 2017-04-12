import datetime
from Queue import PriorityQueue, Queue
from core import LoopixClient, LoopixMixNode, LoopixProvider, generate_all_core
import supportFunctions as sf
import time
import json

with open('config.json') as infile:
    _PARAMS = json.load(infile)

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
    EXP_PARAMS_LOOPS = (float(_PARAMS["parametersMixnodes"]["EXP_PARAMS_LOOPS"]), None)

    def __init__(self, mixnode):
        self.mixnode = mixnode
        self.priority_queue = PriorityQueue()

    def register_providers(self, providers):
        self.mixnode.providers = providers

    def register_mixnodes(self, mixnodes):
        self.mixnode.mixnodes = mixnodes

    def process_message(self, message):
        flag, data = self.mixnode.process_message(message)
        if flag == "RELAY":
            delay, new_message, new_addr = data
            enqueue(self.priority_queue, delay, (new_message, new_addr))

    def send_loop_messages(self):
        while True:
            interval = sf.sampleFromExponential(self.EXP_PARAMS_LOOPS)
            time.sleep(interval)
            enqueue(self.priority_queue, 0, (message, new_addr))


class ProviderHandler(MixNodeHandler):
    def __init__(self, provider):
        MixNodeHandler.__init__(self, provider)
        self.provider = provider
        self.storage = {}

    def register_clients(self, clients):
        self.provider.clients = clients

    def process_message(self, message):
        flag, data = self.provider.process_message(message)
        if flag == "RELAY":
            delay, new_message, new_addr = data
            enqueue(self.priority_queue, delay, (new_message, new_addr))
        elif flag == "STORE":
            new_message, next_name = data
            recipient = self.provider.clients[name]
            new_addr = recipient.host, recipient.port
            self.saveInStorage(name, (new_message, new_addr))

    def saveInStorage(self, key, value):
        if key in self.storage:
            self.storage[key].append(value)
        else:
            self.storage[key] = [value]

    def handle_package(self, data):
        if data[:8] == "PULL_MSG":
            data = self.provider.get_user_messages(data[8:])
            enqueue(self.priority_queue, 0, data)
        else:
            self.process_message(data)


class ClientHandler(object):

    EXP_PARAMS_PAYLOAD = (
        float(_PARAMS["parametersClients"]["EXP_PARAMS_PAYLOAD"]), None)

    EXP_PARAMS_LOOPS = (
        float(_PARAMS["parametersClients"]["EXP_PARAMS_LOOPS"]), None)
    EXP_PARAMS_COVER = (
        float(_PARAMS["parametersClients"]["EXP_PARAMS_COVER"]), None)

    def __init__(self, client):
        self.client = client
        self.priority_queue = PriorityQueue()
        self.buffer_queue = Queue()
        self.inbox = Queue()


    def register_providers(self, providers):
        self.client.providers = providers

    def register_mixnodes(self, mixnodes):
        self.client.mixnodes = mixnodes

    def register_known_clients(self, known_clients):
        self.client.known_clients = known_clients

    def read_mail(self):
        while not self.inbox.empty():
            message = self.inbox.pop()
            processed = self.process_message(message)
            print processed

    def process_message(self, message):
        return self.client.process_message(message)

    def make_loop_stream(self):
        while True:
            interval = sf.sampleFromExponential(self.EXP_PARAMS_LOOPS)
            time.sleep(interval)
            loop_message, next_addr = self.client.create_loop_message()
            enqueue(self.priority_queue, 0, (loop_message, next_addr))

    def make_drop_stream(self):
        while True:
            interval = sf.sampleFromExponential(self.EXP_PARAMS_COVER)
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
            interval = sf.sampleFromExponential(self.EXP_PARAMS_PAYLOAD)
            time.sleep(interval)
            data = self.client.next_message()
            enqueue(self.priority_queue, 0, data)

    def prepare_actual_message(self, message, receiver):
        data = self.client.create_actual_message(message, receiver)
        self.client.buffer.put(data)


env = generate_all_core()

def generate_client_handlers(env):
    client_handlers = []
    for name, client in env.client_objects.iteritems():
        client_handler = ClientHandler(client)
        client_handler.register_providers(env.public_providers)
        client_handler.register_mixnodes(env.public_mixnodes)
        client_handler.register_known_clients(env.public_clients)
        client_handlers.append(client_handler)
    return client_handlers

def generate_mixnode_handlers(env):
    mixnode_handlers = []
    for name, mixnode in env.mixnode_objects.iteritems():
        mixnode_handler = MixNodeHandler(mixnode)
        mixnode_handler.register_providers(env.public_providers)
        mixnode_handler.register_mixnodes(env.public_mixnodes)
        mixnode_handlers.append(mixnode_handler)
    return mixnode_handlers

def generate_provider_handlers(env):
    provider_handlers = []
    for name, provider in env.provider_objects.iteritems():
        provider_handler = ProviderHandler(provider)
        provider_handler.register_providers(env.public_providers)
        provider_handler.register_mixnodes(env.public_mixnodes)
        provider_handler.register_clients(env.public_clients)
        provider_handlers.append(provider_handler)
    return provider_handlers

def generate_all_handlers(env):
    mixnode_handlers = generate_mixnode_handlers(env)
    provider_handlers = generate_provider_handlers(env)
    client_handlers = generate_client_handlers(env)
    return mixnode_handlers, provider_handlers, client_handlers


mixnode_handlers, provider_handlers, client_handlers = generate_all_handlers(env)


client_handler = client_handlers[0]
#client_handler.make_loop_stream()
#client_handler.make_drop_stream()
#client_handler.make_actual_message_stream()
client_handler.make_pull_request_stream()
