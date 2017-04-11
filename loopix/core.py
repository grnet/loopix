import json
import time
import petlib
import random
from collections import OrderedDict
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

    def selectRandomClient(self):
        return random.choice(self.clients)

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




setup_mixes = []
setup_providers = []
setup_clients = []

def generate_key_pair():
    params = SphinxParams()
    o = params.group.G.order()

    priv = o.random()
    pubk = priv * params.group.g
    return priv, pubk

for i in range(3):
    mpriv, mpubk = generate_key_pair()
    mix = Mix('Mix%d'%i, 9000+i, '1.2.3.4', mpubk, i % 3)
    setup_mixes.append((mix, mpriv))


for i in range(3):
    ppriv, ppubk = generate_key_pair()
    provider = Provider('Provider%d'%i, 9010+i, '1.2.3.4', ppubk)
    setup_providers.append((provider, ppriv))

for i in range(3):
    upriv, upubk = generate_key_pair()
    user = User("User%d"%i, 9015+i, '1.2.3.4', upubk, setup_providers[i][0])
    setup_clients.append((user, upriv))



loopix_clients = OrderedDict()
loopix_mixnodes = OrderedDict()
loopix_providers = OrderedDict()

for mix in setup_mixes:
    mix_pubdata, mix_privk = mix
    mix = LoopixMixNode(mix_pubdata.host, mix_pubdata.port, mix_pubdata.name, mix_privk, mix_pubdata.pubk, mix_pubdata.group)
    loopix_mixnodes[mix.name] = mix

for p in setup_providers:
    p_pubdata, p_privk = p
    provider = LoopixProvider(p_pubdata.host, p_pubdata.port, p_pubdata.name, p_privk, p_pubdata.pubk)
    loopix_providers[provider.name] = provider

 
for u in setup_clients:
    u_pubdata, u_privk = u
    user = LoopixClient(u_pubdata.host, u_pubdata.port, u_pubdata.name, u_pubdata.provider, u_privk, u_pubdata.pubk)
    loopix_clients[user.name] = user


public_mixnodes = [x[0] for x in setup_mixes]
public_providers = [x[0] for x in setup_providers]
public_clients = [x[0] for x in setup_clients]

def get_clients_provider(client):
    return loopix_providers[client.provider.name]

test_client = random.choice(loopix_clients.values())
test_provider = get_clients_provider(test_client)
test_provider.clientList = public_clients

pub_mix_path = test_client.takePathSequence(public_mixnodes)
process_path = [test_provider] + loopix_mixnodes.values() + [test_provider]
#-----------------------------CHECK IF LOOPS WORK CORRECT-------------------------
print "CREATE LOOP MESSAGE"
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
print "CREATE DROP MESSAGE"
test_client.providers = public_providers
test_client.clients = public_clients

random_client = test_client.selectRandomClient()
drop_message = test_client.create_drop_message(pub_mix_path, random_client)
rand_prov_obj = loopix_providers[random_client.provider.name]
process_path = [test_provider] + loopix_mixnodes.values() + [rand_prov_obj]
message = drop_message
for entity in process_path:
    flag, lst = entity.process_message(petlib.pack.decode(message))
    print "Flag:", flag
    if flag == "RELAY":
        message = lst[1]
