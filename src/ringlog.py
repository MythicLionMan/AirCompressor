import ustruct as struct
from condlock import CondLock

# Provides an efficient ring buffer for storing logs. The buffer is a
# bytearray, and logs are packed into it, so no allocations are needed
# in order to append a new element. When referencing elements indexes
# are relative to the last element added, so log[0] is the last element,
# log[1] is the previous, etc.
class RingLog:
    def __init__(self, struct_format, field_names, size_limit, thread_safe = False):
        self.size_limit = size_limit
        self.struct_format = struct_format
        self.field_names = field_names
        self.lock = CondLock(thread_safe)

        self.stride = struct.calcsize(struct_format)
        self.data = bytearray(size_limit * self.stride)
        
        self.console_log = False
        self.end_index = -1
        self.count = 0
    
    # Advances the insertion point by 1, and packs a new long into the buffer
    def log(self, log_tuple):
        with self.lock:
            # Advance the end_index to the next available slot in the log
            self.end_index = (self.end_index + 1) % self.size_limit
            self.count = min(self.count + 1, self.size_limit)

            # Assign the tuple to the most recent slot
            self[0] = log_tuple
                
    # Outputs all entries in the log as json pairs without having to allocate one big string
    # NOTE If the blocking parameter is false, then the writer will not be drained. The caller
    #      will not be blocked, but it will also be necessary for the writer to buffer all of
    #      the data, so the memory consumption will be much larger. This is an unfortunate
    #      tradeoff if the caller requires a lock on another thread. In many cases it may be
    #      fine to block the calling thread for the duration of the write, but there is a risk
    #      that if the buffer fill up the caller may be blocked while waiting on the network to
    #      flush (on the flip side, bytes may be lost if the buffer is full. I'm not sure how
    #      this is handled)
    async def dump(self, writer, since, filter_index = 0, blocking = True):
        # TODO It may not be necessary to lock the log for the entire duration of
        #      the write. This could alleviate the need for the blocking parameter.
        #      But it would be necessary to ensure that a new log has not overwriten
        #      one of the logs we're about to send. For now I'll just lock the whole
        #      thing.
        with self.lock:
            if blocking:
                await writer.drain()
            
            first_log = True
            for i in range(self.count):
                log = self[i]
                if log[filter_index] >= since:
                    if not first_log:
                        writer.write(",")
                    first_log = False

                    writer.write("{")
                    first_field = True
                    for field, value in zip(self.field_names, log):
                        if not first_field:
                            writer.write(",")
                        first_field = False
                        
                        # Value may be a binary string. If it is it's string representation
                        # will not be valid json (it will be represented as b'value'). Try
                        # to decode it, and if that fails asume that it's a type with a valid
                        # conversion.
                        try:
                            value = '"' + value.decode() + '"'
                        except:
                            pass
                        
                        writer.write('"' + field + '":' + str(value))
                    writer.write("}")
                    if blocking:
                        await writer.drain()

    def __getitem__(self, index):
        with self.lock:
            wrapped_index = (self.end_index - index) % self.size_limit
            
            return struct.unpack_from(self.struct_format, self.data, wrapped_index * self.stride)

    def __setitem__(self, index, log_tuple):
        with self.lock:
            wrapped_index = (self.end_index - index) % self.size_limit

            struct.pack_into(self.struct_format, self.data, wrapped_index * self.stride, *log_tuple)
        
        if self.console_log:
            print("Logged[{}]: {}".format(wrapped_index, log_tuple))

    def __len__(self):
        with self.lock:
            return self.count
    
    