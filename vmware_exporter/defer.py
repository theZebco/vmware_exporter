'''
Helpers for writing efficient twisted code, optimized for coroutine scheduling efficiency
'''
# autopep8'd

from twisted.internet import defer
from twisted.python import failure


_NO_RESULT = object()


def _passthrough(result):
    return result


class BranchingDeferred(defer.Deferred):

    '''
    This is meant for code where you are doing something like this:

    content = yield self.get_connection_content()
    results = yield defer.DeferredList([
        self.get_hosts(content),
        self.get_datastores(content),
    ])

    This allows get_hosts and get_datastores to run in parallel, which is good.
    But what if you don't want the whole of get_hosts to wait for
    get_connection_content() to be complete?

    We have a bunch of places where it would be better for scheduling if we did this:

    content = self.get_connection_content()
    results = yield defer.DeferredList([
        self.get_hosts(content),
        self.get_datastores(content),
    ])

    Now we don't have to wait for content to be finished before get_hosts etc
    starts running. It is up to get_hosts to block on the content deferred itself.

    (Thats a contrived example, the real win is allowing host_labels and
    vm_inventory to run in parallel).

    Unfortunately you can't have parallel branches blocking on the same deferred
    like this with a standard Twisted deferred: a normal Deferred has a single
    linear callback chain and can only be consumed once.

    This is a "broadcast" deferred: every consumer that adds callbacks (or yields
    it from an inlineCallbacks coroutine) gets its own private Deferred that is
    fired with the shared result. It works across Twisted versions because all of
    the add* entry points (which newer Twisted routes through addBoth, bypassing
    addCallbacks) are overridden to register an independent waiter.
    '''

    def __init__(self):
        super().__init__()
        # (value, is_failure) once fired, otherwise the _NO_RESULT sentinel.
        self._branch_result = _NO_RESULT
        self._branch_waiters = []

    def _register(self, waiter):
        if self._branch_result is _NO_RESULT:
            self._branch_waiters.append(waiter)
        else:
            value, is_failure = self._branch_result
            (waiter.errback if is_failure else waiter.callback)(value)
        return waiter

    def addCallbacks(self, callback, errback=None,
                     callbackArgs=(), callbackKeywords={},
                     errbackArgs=(), errbackKeywords={}):
        waiter = defer.Deferred()
        waiter.addCallbacks(
            callback, errback,
            callbackArgs=callbackArgs, callbackKeywords=callbackKeywords,
            errbackArgs=errbackArgs, errbackKeywords=errbackKeywords,
        )
        return self._register(waiter)

    def addCallback(self, callback, *args, **kwargs):
        return self.addCallbacks(callback, callbackArgs=args, callbackKeywords=kwargs)

    def addErrback(self, errback, *args, **kwargs):
        return self.addCallbacks(_passthrough, errback, errbackArgs=args, errbackKeywords=kwargs)

    def addBoth(self, callback, *args, **kwargs):
        return self.addCallbacks(
            callback, callback,
            callbackArgs=args, callbackKeywords=kwargs,
            errbackArgs=args, errbackKeywords=kwargs,
        )

    def callback(self, result):
        self._branch_fire(result, False)

    def errback(self, fail=None):
        if not isinstance(fail, failure.Failure):
            fail = failure.Failure(fail)
        self._branch_fire(fail, True)

    def _branch_fire(self, value, is_failure):
        self._branch_result = (value, is_failure)
        waiters, self._branch_waiters = self._branch_waiters, []
        for waiter in waiters:
            (waiter.errback if is_failure else waiter.callback)(value)


class run_once_property(object):

    '''
    This is a property descriptor that caches the first result it retrieves. It
    does this by setting keys in self.__dict__ on the parent class instance.
    This is fast - python won't even bother running our descriptor next time
    because attributes in self.__dict__ on a class instance trump descriptors
    on the class.

    This is intended to be used with the Collector class which has a request
    bound lifecycle (this isn't going to cache stuff forever and cause memory
    leaks).
    '''

    def __init__(self, callable):
        self.callable = callable

    def __get__(self, obj, cls):
        if obj is None:
            return self
        result = obj.__dict__[self.callable.__name__] = BranchingDeferred()
        self.callable(obj).chainDeferred(result)
        return result


@defer.inlineCallbacks
def parallelize(*args):
    results = yield defer.DeferredList(args, fireOnOneErrback=True)
    return tuple(r[1] for r in results)
