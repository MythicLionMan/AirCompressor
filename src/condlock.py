import _thread

# CondLock is a task synchronization lock that can be configured to
# not lock when synchronization is not needed (or not possible). It
# is also reentrant, so that the same thread can aquire it multiple
# times.
class CondLock:
    def __init__(self, thread_safe):
        if thread_safe:
            self.lock = _thread.allocate_lock()
        else:
            self.lock = None            
        self.lock_thread = None
        self.depth = 0
        
    def locked(self):
        return self.lock.locked() if self.lock else False
        
    def __enter__(self):
        if self.lock:
            thread_id = _thread.get_ident()            
            # It is possible that any thread is in the code here, and the
            # value of lock_thread may change while we're checking it. But
            # it cannot change to be == thread_id, since this is the only
            # thread that will change it to thread_id
            if self.lock_thread == thread_id:
                # We must be running on the thread that has aquired the lock.
                # No need to aquire it again (and it would deadlock if we did).
                # We're also safe to modify depth without aquiring another lock,
                # since this thread already has the lock
                self.depth = self.depth + 1
                return self
            
            # The current thread has not aquired the lock
            self.lock.acquire()
            self.lock_thread = thread_id
            
        return self
        
    def __exit__(self, *args):
        if self.lock:
            # At this point only a thread that has aquired the lock may enter
            # this section.
            if self.depth and self.lock_thread:
                # This is not the call that aquired the lock. Decrement the count
                # and return without releasing the lock
                self.depth = self.depth - 1
                return

            self.lock_thread = None
            self.lock.release()
            
