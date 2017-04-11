import json
import time
import petlib
import random
from collections import OrderedDict, namedtuple
from sphinxmix.SphinxClient import Nenc, create_forward_message, PFdecode, \
    Relay_flag, Dest_flag, receive_forward
from sphinxmix.SphinxParams import SphinxParams
from sphinxmix.SphinxNode import sphinx_process
from format3 import Mix, Provider, User

#from loopix import supportFunctions as sf
import supportFunctions as sf

with open('config.json') as infile:
    _PARAMS = json.load(infile)

MAX_RETRIEVE = 500


def makeSphinxPacket(params, exp_delay, receiver, path, message,
                     dropFlag=False):
    path.append(receiver)
    keys_nodes = [n.pubk for n in path]
    nodes_routing = []
    path_length = len(path)
    for i, node in enumerate(path):
        if exp_delay == 0.0:
            delay = 0.0
        else:
            delay = sf.sampleFromExponential((exp_delay, None))
        drop = dropFlag and i == path_length - 1
        print node.host, node.port, drop, delay, node.name
        entry = Nenc([(node.host, node.port), drop, delay, node.name])
        nodes_routing.append(entry)

    # Destination of the message
    dest = (receiver.host, receiver.port, receiver.name)
    header, body = create_forward_message(
        params, nodes_routing, keys_nodes, dest, message)
    return (header, body)


class LoopixClient(object):
    PATH_LENGTH = int(_PARAMS["parametersClients"]["PATH_LENGTH"])
    EXP_PARAMS_PAYLOAD = (
        float(_PARAMS["parametersClients"]["EXP_PARAMS_PAYLOAD"]), None)

    EXP_PARAMS_LOOPS = (
        float(_PARAMS["parametersClients"]["EXP_PARAMS_LOOPS"]), None)
    EXP_PARAMS_COVER = (
        float(_PARAMS["parametersClients"]["EXP_PARAMS_COVER"]), None)
    EXP_PARAMS_DELAY = float(_PARAMS["parametersClients"]["EXP_PARAMS_DELAY"])
    NOISE_LENGTH = float(_PARAMS["parametersClients"]["NOISE_LENGTH"])

    def __init__(self, host, port, name, provider, privk, pubk):
        self.host = host
        self.port = port
        self.name = name
        self.provider = provider
        self.privk = privk
        self.pubk = pubk
        self.params = SphinxParams(header_len=1024)
        self.buffer = []

    def register_providers(self, providers):
        self.providers = providers

    def register_mixnodes(self, mixnodes):
        self.mixnodes = mixnodes

    def register_known_clients(self, known_clients):
        self.known_clients = known_clients

    def selectRandomClient(self):
        return random.choice(self.known_clients.values())

    def create_drop_message(self, mixers, random_client):
        randomMessage = sf.generateRandomNoise(self.NOISE_LENGTH)
        random_provider = random_client.provider
        path = [self.provider] + mixers + [random_provider]
        (header, body) = makeSphinxPacket(
            self.params, self.EXP_PARAMS_DELAY,
            random_client, path, randomMessage, dropFlag=True)
        return petlib.pack.encode((header, body))

    def create_loop_message(self, mixers, timestamp):
        path = [self.provider] + mixers + [self.provider]
        heartMsg = sf.generateRandomNoise(self.NOISE_LENGTH)
        (header, body) = makeSphinxPacket(
            self.params, self.EXP_PARAMS_DELAY,
            self, path, 'HT' + heartMsg + str(timestamp), dropFlag=False)
        return petlib.pack.encode((header, body))

    def next_message(self, mixList):
        if len(self.buffer) > 0:
            return self.buffer.pop(0)
        else:
            return self.create_drop_message(mixList)

    def get_buffered_message(self):
        while True:
            interval = sf.sampleFromExponential(self.EXP_PARAMS_PAYLOAD)
            time.sleep(interval)
            yield self.next_message()

    def decrypt_message(self, message):
        (header, body) = message
        peeledData = sphinx_process(self.params, self.privk, header, body)
        (tag, info, (header, body)) = peeledData
        routing = PFdecode(self.params, info)
        if routing[0] == Dest_flag:
            dest, message = receive_forward(self.params, body)
            if dest[-1] == self.name:
                return message
            else:
                raise Exception("Destination did not match")

    def process_message(self, data):
        try:
            message = petlib.pack.decode(data)
            msg = self.decrypt_message(message)
            if msg.startswith("HT"):
                print "[%s] > Heartbeat looped back" % self.name
            else:
                print "[%s] > New message unpacked." % (self.name)
            return msg
        except Exception, e:
            print "[%s] > ERROR: Message reading error: %s" % (self.name, str(e))
            print data

    def takePathSequence(self, mixnet):
        """ Function takes a random path sequence build of active mixnodes. If the
        default length of the path is bigger that the number of available mixnodes,
        then all mixnodes are used as path.

                Args:
                mixnet (list) - list of active mixnodes,
        """
        ENTRY_NODE = 0
        MIDDLE_NODE = 1
        EXIT_NODE = 2

        randomPath = []
        try:
            entries = [x for x in mixnet if x.group == ENTRY_NODE]
            middles = [x for x in mixnet if x.group == MIDDLE_NODE]
            exits = [x for x in mixnet if x.group == EXIT_NODE]

            entryMix = random.choice(entries)
            middleMix = random.choice(middles)
            exitMix = random.choice(exits)

            randomPath = [entryMix, middleMix, exitMix]
            return randomPath
        except Exception, e:
            print "[%s] > ERROR: During path generation: %s" % (self.name, str(e))



class LoopixMixNode(object):
    PATH_LENGTH = 3
    EXP_PARAMS_DELAY = (float(_PARAMS["parametersMixnodes"]["EXP_PARAMS_DELAY"]), None)
    EXP_PARAMS_LOOPS = (float(_PARAMS["parametersMixnodes"]["EXP_PARAMS_LOOPS"]), None)
    TAGED_HEARTBEATS = _PARAMS["parametersMixnodes"]["TAGED_HEARTBEATS"]
    NOISE_LENGTH = float(_PARAMS["parametersMixnodes"]["NOISE_LENGTH"])

    def __init__(self, host, port, name, privk, pubk, group=None):
        self.host = host
        self.port = port
        self.name = name
        self.privk = privk
        self.pubk = pubk
        self.params = SphinxParams(header_len=1024)
        self.group = group

    def register_providers(self, providers):
        self.providers = providers

    def register_mixnodes(self, mixnodes):
        self.mixnodes = mixnodes

    def createSphinxHeartbeat(self, mixers, timestamp):
        heartMsg = sf.generateRandomNoise(self.NOISE_LENGTH)
        header, body = makeSphinxPacket(
            self.params, self.EXP_PARAMS_DELAY, self, mixers, 'HT' + heartMsg)
        return (header, body)

    def process_sphinx_packet(self, message):
        header, body = message
        ret_val = sphinx_process(self.params, self.privk, header, body)
        return ret_val

    def handle_relay(self, header, body, meta_info):
        next_addr, dropFlag, delay, next_name = meta_info
        new_message = petlib.pack.encode((header, body))
        return "RELAY", [delay, new_message, next_addr]

    def process_message(self, data):
        peeledData = self.process_sphinx_packet(data)
        (tag, info, (header, body)) = peeledData
        # routing_flag, meta_info = PFdecode(self.params, info)
        routing = PFdecode(self.params, info)
        print routing
        routing_flag, meta_info = routing
        next_addr, dropFlag, delay, next_name = meta_info
        if routing[0] == Relay_flag:
            return self.handle_relay(header, body, meta_info)
        elif routing[0] == Dest_flag:
            dest, message = receive_forward(self.params, body)
            print "[%s] > Message received" % self.name
            if dest[-1] != self.name:
                raise Exception("Destionation did not match")
            if message.startswith('HT'):
                print "[%s] > Heartbeat looped pack" % self.name
                return "DEST", [message]
        else:
            print 'Flag not recognized'



class LoopixProvider(LoopixMixNode):
    def __init__(self, *args, **kwargs):
        LoopixMixNode.__init__(self, *args, **kwargs)
        self.storage = {}
        self.clientList = []

    def register_client_list(self, client_list):
        self.client_list = client_list

    def saveInStorage(self, key, value):
        if key in self.storage:
            self.storage[key].append(value)
        else:
            self.storage[key] = [value]

    def handle_package(self, data):
        if data[:8] == "PULL_MSG":
            return self.get_user_messages(data[8:])
        return self.process_message(data)

    def get_user_messages(self, name):
        if name in self.storage:
            messages = self.storage[name]
            popped, rest = messages[:MAX_RETRIEVE], messages[MAX_RETRIEVE:]
            self.storage[name] = rest
            return popped
        return []

    def handle_relay(self, header, body, meta_info):
        next_addr, dropFlag, delay, next_name = meta_info
        if dropFlag:
            return "DROP", []
        new_message = petlib.pack.encode((header, body))
        if next_name in self.clientList:
            return "STORE", [new_message, next_name]
        else:
            return "RELAY", [delay, new_message, next_addr]


def generate_key_pair():
    params = SphinxParams()
    o = params.group.G.order()

    priv = o.random()
    pubk = priv * params.group.g
    return priv, pubk


def generate_mixnodes(n=3):
    public_mixnodes = OrderedDict()
    mixnode_objects = OrderedDict()
    for i in range(n):
        privk, pubk = generate_key_pair()
        mix = Mix('Mix%d'%i, 9000+i, '1.2.3.4', pubk, i % 3)
        name = mix.name
        mix_obj = LoopixMixNode(
            mix.host, mix.port, name, privk, pubk, mix.group)
        public_mixnodes[name] = mix
        mixnode_objects[name] = mix_obj
    return public_mixnodes, mixnode_objects


def generate_providers(n=3):
    public_providers = OrderedDict()
    provider_objects = OrderedDict()
    for i in range(n):
        privk, pubk = generate_key_pair()
        provider = Provider('Provider%d'%i, 9010+i, '1.2.3.4', pubk)
        name = provider.name
        provider_obj = LoopixProvider(
            provider.host, provider.port, provider.name, privk, pubk)
        public_providers[name] = provider
        provider_objects[name] = provider_obj
    return public_providers, provider_objects


def generate_clients(public_providers, n=3):
    public_clients = OrderedDict()
    client_objects = OrderedDict()
    for i in range(n):
        provider = random.choice(public_providers.values())
        privk, pubk = generate_key_pair()
        client = User('User%d'%i, 9020+i, '1.2.3.4', pubk, provider)
        name = client.name
        client_obj = LoopixClient(
            client.host, client.port, client.name, provider, privk, pubk)
        public_clients[name] = client
        client_objects[name] = client_obj
    return public_clients, client_objects


Env = namedtuple("Env",
                 ["public_mixnodes", "mixnode_objects",
                  "public_providers", "provider_objects",
                  "public_clients", "client_objects"])


def generate_all():
    public_mixnodes, mixnode_objects = generate_mixnodes()
    public_providers, provider_objects = generate_providers()
    public_clients, client_objects = generate_clients(public_providers)

    for name, client in client_objects.iteritems():
        client.register_providers(public_providers)
        client.register_mixnodes(public_mixnodes)
        client.register_known_clients(public_clients)

    for name, mixnode in mixnode_objects.iteritems():
        mixnode.register_providers(public_providers)
        mixnode.register_mixnodes(public_mixnodes)

    for name, provider in provider_objects.iteritems():
        provider.register_providers(public_providers)
        provider.register_mixnodes(public_mixnodes)
        provider.register_client_list(public_clients.values())

    return Env(public_mixnodes, mixnode_objects,
               public_providers, provider_objects,
               public_clients, client_objects)


def get_clients_provider(client, env):
    return env.provider_objects[client.provider.name]


def check_loop_message(test_client, env):
    print "CREATE LOOP MESSAGE"
    test_provider = get_clients_provider(test_client, env)

    pub_mix_path = test_client.takePathSequence(env.public_mixnodes.values())
    process_path = [test_provider] + env.mixnode_objects.values() + [test_provider]

    loop_message = test_client.create_loop_message(pub_mix_path, time.time())

    print test_client.provider
    print [e.name for e in process_path]
    message = loop_message
    for entity in process_path:
        flag, lst = entity.process_message(petlib.pack.decode(message))
        print "Flag:", flag
        if flag == "RELAY":
            message = lst[1]

    test_client.process_message(message)

#-----------------------------CHECK IF DROP MESSAGE WORKS CORRECT-------------------------
def check_drop_message(test_client, env):
    print "CREATE DROP MESSAGE"
    test_provider = get_clients_provider(test_client, env)
    pub_mix_path = test_client.takePathSequence(env.public_mixnodes.values())
    random_client = test_client.selectRandomClient()
    drop_message = test_client.create_drop_message(pub_mix_path, random_client)
    rand_prov_obj = env.provider_objects[random_client.provider.name]
    process_path = [test_provider] + env.mixnode_objects.values() + [rand_prov_obj]
    message = drop_message
    for entity in process_path:
        flag, lst = entity.process_message(petlib.pack.decode(message))
        print "Flag:", flag
        if flag == "RELAY":
            message = lst[1]

def test():
    env = generate_all()
    test_client = random.choice(env.client_objects.values())
    check_loop_message(test_client, env)
    check_drop_message(test_client, env)


if __name__ == "__main__":
    test()
