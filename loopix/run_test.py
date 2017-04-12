from sphinxmix.SphinxParams import SphinxParams
from collections import OrderedDict, namedtuple
from format3 import Mix, Provider, User
from core import LoopixMixNode, LoopixProvider, LoopixClient, takeMixNodesSequence
import random
from networking import MixNodeHandler, ProviderHandler, ClientHandler, \
    process_queue, ThreadSafeDict
import petlib
from Queue import Queue
from threading import Thread


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


def generate_all_core():
    public_mixnodes, mixnode_objects = generate_mixnodes()
    public_providers, provider_objects = generate_providers()
    public_clients, client_objects = generate_clients(public_providers)

    return Env(public_mixnodes, mixnode_objects,
               public_providers, provider_objects,
               public_clients, client_objects)


def generate_client_handlers(env):
    client_handlers = {}
    for name, client in env.client_objects.iteritems():
        client_handler = ClientHandler(client)
        client_handler.register_providers(env.public_providers)
        client_handler.register_mixnodes(env.public_mixnodes)
        client_handler.register_known_clients(env.public_clients)
        client_handlers[name] = client_handler
    return client_handlers

def generate_mixnode_handlers(env):
    mixnode_handlers = {}
    for name, mixnode in env.mixnode_objects.iteritems():
        mixnode_handler = MixNodeHandler(mixnode)
        mixnode_handler.register_providers(env.public_providers)
        mixnode_handler.register_mixnodes(env.public_mixnodes)
        mixnode_handlers[name] = mixnode_handler
    return mixnode_handlers

def generate_provider_handlers(env):
    provider_handlers = {}
    for name, provider in env.provider_objects.iteritems():
        provider_handler = ProviderHandler(provider)
        provider_handler.register_providers(env.public_providers)
        provider_handler.register_mixnodes(env.public_mixnodes)
        provider_handler.register_clients(env.public_clients)
        provider_handlers[name] = provider_handler
    return provider_handlers

Handlers = namedtuple("Handlers", ["mixnode_handlers", "provider_handlers", "client_handlers"])

def generate_all_handlers(env):
    mixnode_handlers = generate_mixnode_handlers(env)
    provider_handlers = generate_provider_handlers(env)
    client_handlers = generate_client_handlers(env)
    return Handlers(mixnode_handlers, provider_handlers, client_handlers)


def make_inboxes(env):
    INBOXES = ThreadSafeDict()
    with INBOXES.lock() as d:
        for entity in env.public_mixnodes.values()\
            + env.public_providers.values()\
            + env.public_clients.values():
            d[(entity.host, entity.port)] = Queue()
    return INBOXES


def launch(target, args=()):
    t = Thread(target=target, args=args)
    t.start()


def demo():
    env = generate_all_core()
    handlers = generate_all_handlers(env)
    INBOXES = make_inboxes(env)

    for mhandler in handlers.mixnode_handlers.values():
        addr = mhandler.mixnode.host, mhandler.mixnode.port
        with INBOXES.lock() as d:
            inbox = d[addr]
        launch(mhandler.process_inbox, args=(inbox,))
        launch(mhandler.send_loop_messages)
        launch(process_queue, args=(mhandler, INBOXES))

    for phandler in handlers.provider_handlers.values():
        addr = phandler.provider.host, phandler.provider.port
        with INBOXES.lock() as d:
            inbox = d[addr]
        launch(phandler.process_inbox, args=(inbox,))
        launch(phandler.send_loop_messages)
        launch(process_queue, args=(phandler, INBOXES))

    # make_fake_real_traffic(env, handlers.client_handlers.values())

    for chandler in [handlers.client_handlers.values()[0]]:
        addr = chandler.client.host, chandler.client.port
        with INBOXES.lock() as d:
            inbox = d[addr]
        launch(chandler.read_mail, args=(inbox,))
        launch(chandler.make_actual_message_stream)
        launch(chandler.make_loop_stream)
        launch(chandler.make_drop_stream)
        launch(chandler.make_pull_request_stream)
        launch(process_queue, args=(chandler, INBOXES))


def make_fake_real_traffic(env, client_handlers):
    for ch in client_handlers:
        message = "Hellow World from %s" % ch.client.name
        random_recipient = ch.client.selectRandomClient()
        
        packet = ch.client.create_actual_message(message, random_recipient)
        ch.buffer_queue.put(packet)
        print "PUTTED INTO BUFFER"

def check_loop_message(client_handler, env):
    print "CREATE LOOP MESSAGE"
    test_provider = get_clients_provider(client_handler.client, env)
    
    pub_mix_path = takeMixNodesSequence(env.public_mixnodes.values())
    process_path = [test_provider] + env.mixnode_objects.values() + [test_provider]

    loop_message, next_addr = client_handler.client.create_loop_message()

    print [e.name for e in process_path]
    message = loop_message
    for entity in process_path:
        flag, lst = entity.process_message(message)
        print "Flag:", flag
        if flag == "RELAY":
            message = lst[1]
        if flag == "STORE":
            message = lst[0]

    client_handler.client.process_message(message)
    

def get_clients_provider(client, env):
    return env.provider_objects[client.provider.name]


def check_drop_message(client_handler, env):
    print "CREATE DROP MESSAGE"
    test_provider = get_clients_provider(client_handler.client, env)
    pub_mix_path = takeMixNodesSequence(env.public_mixnodes.values())
    random_client = client_handler.client.selectRandomClient()

    drop_message, next_addr = client_handler.client.create_drop_message(random_client)
    rand_prov_obj = env.provider_objects[random_client.provider.name]
    process_path = [test_provider] + env.mixnode_objects.values() + [rand_prov_obj]
    message = drop_message
    for entity in process_path:
        flag, lst = entity.process_message(message)
        print "Flag:", flag
        if flag == "RELAY":
            message = lst[1]    


def test():
    env = generate_all_core()
    handlers = generate_all_handlers(env)

    test_client = random.choice(handlers.client_handlers.values())
    check_loop_message(test_client, env)
    check_drop_message(test_client, env)

if __name__ == "__main__":
    demo()



