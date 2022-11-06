import _thread

# EmptyLock can be used in place of a task synchronization
# lock when running in thread unsafe mode. It always returns
# the lock immediately, and does nothing nothing when entered
# or exited.
class EmptyLock:
    def __enter__(self):
        return self
         
    def __exit__(self, *args):
        pass
    
    @classmethod
    def create_lock(cls, thread_safe):
        return _thread.allocate_lock() if thread_safe else EmptyLock()
        