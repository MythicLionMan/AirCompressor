import ustruct as struct

# Provides an efficient ring buffer for storing logs. The buffer is a
# bytearray, and logs are packed into it, so no allocations are needed
# in order to append a new element. When referencing elements indexes
# are relative to the last element added, so log[0] is the last element,
# log[1] is the previous, etc.
class RingLog:
    def __init__(self, struct_format, field_names, size_limit):
        self.size_limit = size_limit
        self.struct_format = struct_format
        self.field_names = field_names

        self.stride = struct.calcsize(struct_format)
        self.data = bytearray(size_limit * self.stride)
        
        self.console_log = False
        self.end_index = -1
        self.count = 0
    
    # Advances the insertion point by 1, and packs a new long into the buffer
    def log(self, log_tuple):
        # Advance the end_index to the next available slot in the log
        self.end_index = (self.end_index + 1) % self.size_limit
        self.count = min(self.count + 1, self.size_limit)

        # Assign the tuple to the most recent slot
        self[0] = log_tuple
                
    # Outputs all entries in the log as json pairs without having to allocate one big string
    async def dump(self, writer, since, filter_index = 0):
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
                await writer.drain()
        
    def __getitem__(self, index):
        wrapped_index = (self.end_index - index) % self.size_limit
            
        return struct.unpack_from(self.struct_format, self.data, wrapped_index * self.stride)

    def __setitem__(self, index, log_tuple):
        wrapped_index = (self.end_index - index) % self.size_limit

        struct.pack_into(self.struct_format, self.data, wrapped_index * self.stride, *log_tuple)
            
        if self.console_log:
            print("Logged[{}]: {}".format(wrapped_index, log_tuple))        
        
    def __len__(self):
        return self.count
    