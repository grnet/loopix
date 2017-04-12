import json
import time
import petlib
import random
from Queue import Queue
from collections import OrderedDict, namedtuple
from sphinxmix.SphinxClient import Nenc, create_forward_message, PFdecode, \
    Relay_flag, Dest_flag, receive_forward
from sphinxmix.SphinxParams import SphinxParams
from sphinxmix.SphinxNode import sphinx_process
from format3 import Mix, Provider, User

import supportFunctions as sf

with open('config.json') as infile:
    _PARAMS = json.load(infile)


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
        #print "PACKING", node.host, node.port, drop, delay, node.name
        entry = Nenc([(node.host, node.port), drop, delay, node.name])
        nodes_routing.append(entry)

    # Destination of the message
    dest = (receiver.host, receiver.port, receiver.name)
    header, body = create_forward_message(
        params, nodes_routing, keys_nodes, dest, message)
    return (header, body)


def takeMixNodesSequence(mixnet):
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
        print "ERROR: During path generation: %s" % str(e)


class LoopixClient(object):
    PATH_LENGTH = int(_PARAMS["parametersClients"]["PATH_LENGTH"])
    EXP_PARAMS_DELAY = float(_PARAMS["parametersClients"]["EXP_PARAMS_DELAY"])
    EXP_PARAMS_DELAY = 0.0001
    NOISE_LENGTH = float(_PARAMS["parametersClients"]["NOISE_LENGTH"])

    def __init__(self, host, port, name, provider, privk, pubk):
        self.host = host
        self.port = port
        self.name = name
        self.provider = provider
        self.privk = privk
        self.pubk = pubk
        self.params = SphinxParams(header_len=1024)

    def selectRandomClient(self):
        return random.choice(self.known_clients.values())

    def create_drop_message(self, random_client):
        randomMessage = sf.generateRandomNoise(self.NOISE_LENGTH)
        random_provider = random_client.provider

        mixes = takeMixNodesSequence(self.mixnodes.values())
        path = [self.provider] + mixes + [random_provider]
        (header, body) = makeSphinxPacket(
            self.params, self.EXP_PARAMS_DELAY,
            random_client, path, randomMessage, dropFlag=True)
        drop_message = petlib.pack.encode((header, body))
        next_addr = (self.provider.host, self.provider.port)
        return (drop_message, next_addr)

    def create_loop_message(self):
        mixes = takeMixNodesSequence(self.mixnodes.values())
        path = [self.provider] + mixes + [self.provider]
        heartMsg = sf.generateRandomNoise(self.NOISE_LENGTH)
        
        (header, body) = makeSphinxPacket(
            self.params, self.EXP_PARAMS_DELAY,
            self, path, 'HT' + heartMsg, dropFlag=False)
        
        loop_message = petlib.pack.encode((header, body))
        next_addr = (self.provider.host, self.provider.port)
        return (loop_message, next_addr)

    def create_actual_message(self, message, receiver):
        mixers = takeMixNodesSequence(self.mixnodes.values())
        path = [self.provider] + mixers + [receiver.provider]
        (header, body) = makeSphinxPacket(
            self.params, self.EXP_PARAMS_DELAY,
            receiver, path, message, dropFlag=False)
        packed_message = petlib.pack.encode((header, body))
        next_addr = (self.provider.host, self.provider.port)
        return packed_message, next_addr

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
                print "[%s] > HEARTBEAT RECEIVED BACK" % self.name
            else:
                print "[%s] > NEW MESSAGE RECEIVED" % (self.name)
            return msg
        except Exception, e:
            print "[%s] > ERROR: Message reading error: %s" % (self.name, str(e))


class LoopixMixNode(object):
    PATH_LENGTH = 3
    EXP_PARAMS_DELAY = float(_PARAMS["parametersMixnodes"]["EXP_PARAMS_DELAY"])
    NOISE_LENGTH = float(_PARAMS["parametersMixnodes"]["NOISE_LENGTH"])

    def __init__(self, host, port, name, privk, pubk, group=None):
        self.host = host
        self.port = port
        self.name = name
        self.privk = privk
        self.pubk = pubk
        self.params = SphinxParams(header_len=1024)
        self.group = group

    def create_loop_message(self):
        path = takeMixNodesSequence(self.mixnodes.values())
        heartMsg = sf.generateRandomNoise(self.NOISE_LENGTH)
        header, body = makeSphinxPacket(
            self.params, self.EXP_PARAMS_DELAY, self, path, 'HT' + heartMsg)
        new_message = petlib.pack.encode((header, body))
        new_addr = path[0].host, path[0].port
        return new_message, new_addr

    def process_sphinx_packet(self, message):
        header, body = message
        ret_val = sphinx_process(self.params, self.privk, header, body)
        return ret_val

    def handle_relay(self, header, body, meta_info):
        next_addr, dropFlag, delay, next_name = meta_info
        new_message = petlib.pack.encode((header, body))
        return "RELAY", [delay, new_message, next_addr]

    def process_message(self, data):
        message = petlib.pack.decode(data)
        peeledData = self.process_sphinx_packet(message)
        (tag, info, (header, body)) = peeledData
        # routing_flag, meta_info = PFdecode(self.params, info)
        routing = PFdecode(self.params, info)
        if routing[0] == Relay_flag:
            routing_flag, meta_info = routing
            next_addr, dropFlag, delay, next_name = meta_info
            return self.handle_relay(header, body, meta_info)
        elif routing[0] == Dest_flag:
            dest, message = receive_forward(self.params, body)
            if dest[-1] != self.name:
                raise Exception("Destionation did not match")
            if message.startswith('HT'):
                print "[%s] > HEARTBEAT RECEIVED BACK" % self.name
                return "DEST", [message]
        else:
            print 'Flag not recognized'



class LoopixProvider(LoopixMixNode):
    def __init__(self, *args, **kwargs):
        LoopixMixNode.__init__(self, *args, **kwargs)

    def handle_relay(self, header, body, meta_info):
        next_addr, dropFlag, delay, next_name = meta_info
        if dropFlag:
            return "DROP", []
        new_message = petlib.pack.encode((header, body))
        if next_name in self.clients:
            return "STORE", [new_message, next_name]
        else:
            return "RELAY", [delay, new_message, next_addr]
