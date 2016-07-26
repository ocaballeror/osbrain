import time
import random
from osbrain import run_agent
from osbrain import run_nameserver


def log_a(agent, message):
    agent.log_info('Log a: %s' % message)


def log_b(agent, message):
    agent.log_info('Log b: %s' % message)


if __name__ == '__main__':

    # System deployment
    ns = run_nameserver()
    alice = run_agent('Alice', ns)
    bob = run_agent('Bob', ns)
    eve = run_agent('Eve', ns)
    dave = run_agent('Dave', ns)

    # System configuration
    addr = alice.bind('PUB', alias='main')
    bob.connect(addr, handler={'a': log_a, 'b': log_b})
    eve.connect(addr, handler={'a': log_a})
    dave.connect(addr, handler={'b': log_b})

    # Send messages
    while True:
        time.sleep(1)
        topic = random.choice(['a', 'b'])
        message = 'Hello, %s!' % topic
        alice.send('main', message, topic=topic)
