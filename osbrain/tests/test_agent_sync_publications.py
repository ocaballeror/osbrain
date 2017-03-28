"""
Test file for synchronized publications.
"""
import time

import pytest

from osbrain import Agent
from osbrain import run_agent
from osbrain import run_logger

from common import nsproxy  # pragma: no flakes
from common import sync_agent_logger
from common import logger_received
from common import wait_agent_list


class Server(Agent):
    def on_init(self):
        self.count = 0
        self.received = []
        self.bind('SYNC_PUB', alias='publish', handler='reply')

    def publish(self):
        self.count += 1
        self.send('publish', self.count)

    def publish_str(self):
        self.count += 1
        self.send('publish', str(self.count), topic='positive')
        self.send('publish', str(-self.count), topic='negative')

    def reply(self, request):
        self.received.append((self.count, request))
        return self.count + 0.5


class ServerYield(Server):
    def reply(self, request):
        yield self.count + 0.5
        self.received.append((self.count, request))


class ServerLate(Server):
    def reply(self, delay):
        self.received.append(delay)
        time.sleep(delay)
        return 'x' + str(delay)


class Client(Agent):
    def on_init(self):
        self.received = []


def receive(agent, response):
    agent.received.append(response)


def receive_negate(agent, response):
    agent.received.append(-response)


def on_error(agent):
    agent.error_count += 1


def test_simple_pub(nsproxy):
    """
    SYNC_PUB should work just like a normal PUB.

    When clients connect to a SYNC_PUB server, as long as they do not make
    requests, this communication pattern should behave exactly like a normal
    PUB-SUB pattern.
    """
    server = run_agent('server', base=Server)
    both = run_agent('both', base=Client)
    positive = run_agent('positive', base=Client)

    # Connect clients
    addr = server.addr('publish')
    addr_both = both.connect(addr, handler=receive)
    addr_positive = positive.connect(addr, handler={'positive': receive})
    assert addr_both == addr.twin()
    assert addr_positive == addr.twin()

    # Publish from server
    server.each(0, 'publish_str')

    # Wait for clients to receive some data
    N = 10
    assert wait_agent_list(both, length=N)
    assert wait_agent_list(positive, length=N)

    # both
    received = [int(x) for x in both.get_attr('received')]
    assert len(received) >= N
    for i in range(1, len(received)):
        if received[i] > 0:
            assert received[i - 1] == 1 - received[i]
        else:
            assert received[i - 1] == -received[i]

    # positive
    received = [int(x) for x in positive.get_attr('received')]
    assert len(received) >= N
    assert received == list(range(received[0], received[-1] + 1))


@pytest.mark.parametrize('server', [Server, ServerYield])
def test_request(nsproxy, server):
    """
    Synchronous publish-subscribe pattern with a client that makes a request.

    In this test there is one SYNC_PUB server and two SYNC_SUB clients. The
    server is publishing messages when one of the clients makes a request.
    The response to that request must only be received by the requester.

    It also verifies that the response is processed by the client with a
    different handler, which must be set for each request sent to the
    publisher.
    """
    server = run_agent('server', base=server)
    active = run_agent('active_client', base=Client)
    passive = run_agent('passive_client', base=Client)

    # Connect clients
    server_addr = server.addr('publish')
    active_addr = active.connect(server_addr, alias='sub', handler=receive)
    passive_addr = passive.connect(server_addr, alias='sub', handler=receive)
    assert active_addr == server_addr.twin()
    assert passive_addr == server_addr.twin()

    # Publish from server
    server.each(0, 'publish')

    # Wait for clients to receive some data
    N = 10
    assert wait_agent_list(active, length=N)
    assert wait_agent_list(passive, length=N)

    # Send request from active client
    active.send('sub', 'request!', handler=receive_negate)

    # Server request processing
    assert wait_agent_list(server, length=1)
    received = server.get_attr('received')
    assert len(received) == 1
    assert received[0][1] == 'request!'
    instant = received[0][0]

    # Make sure active gets response
    N = len(active.get_attr('received')) + 2
    assert wait_agent_list(active, length=N)

    # Check active client received data
    received = active.get_attr('received')
    response = instant + 0.5
    assert len(received) >= N
    assert -response in received
    index = received.index(-response)
    assert received[index - 1] + 1 == received[index + 1]
    received.remove(-response)
    assert received == list(range(received[0], received[-1] + 1))

    # Check passive client received data
    assert wait_agent_list(passive, data=received[-1])
    received = passive.get_attr('received')
    assert -response not in received
    assert received == list(range(received[0], received[-1] + 1))


def test_wait(nsproxy):
    """
    Asynchronous request-reply pattern maximum wait.

    When a client makes a request, it can also set a maximum wait time and
    a function to be executed in case the message is not received after that
    period.
    """
    server = run_agent('server', base=ServerLate)
    client = run_agent('client', base=Client)
    logger = run_logger('logger')
    client.set_logger(logger)
    sync_agent_logger(client, logger)

    # Connect clients
    server_addr = server.addr('publish')
    client.connect(server_addr, alias='sub', handler=receive)

    # Publish from server
    server.each(0, 'publish')

    # Wait for client to receive some data
    N = 10
    assert wait_agent_list(client, length=N)

    # Response received in time
    fast = 0
    client.send('sub', fast, handler=receive, wait=0.5)
    time.sleep(0.2)
    assert server.get_attr('received') == [fast]
    assert 'x' + str(fast) in client.get_attr('received')

    # Response not received in time
    slow = 1
    client.send('sub', slow, handler=receive, wait=0.1)
    assert logger_received(logger,
                           log_name='log_history_warning',
                           message='not receive req',
                           timeout=0.5)
    assert server.get_attr('received') == [fast, slow]
    assert 'x' + str(slow) not in client.get_attr('received')

    # Response not received in time with error handler
    slow = 1
    client.send('sub', slow, handler=receive, wait=0.1, on_error=on_error)
    assert wait_agent_list(client, name='error_count', data=1, timeout=0.5)
    assert server.get_attr('received') == [fast, slow]
    assert 'x' + str(slow) not in client.get_attr('received')