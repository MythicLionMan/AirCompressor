class RingLog:
    def __init__(self, LogEntry, size_limit):
        self.data = []
        self.size_limit = size_limit
        self.end_index = -1
        self.LogEntry = LogEntry
        self.console_log = False
    
    def log(self, log_tuple):
        end_index = self.end_index
        size_limit = self.size_limit

        if len(self.data) < size_limit:
            self.data.append(log_tuple)
            end_index += 1
        else:
            end_index = (end_index + 1) % size_limit
            self.data[end_index] = log_tuple
            
        self.end_index = end_index

        if self.console_log:
            print("Logged[{}]: {}".format(end_index, log_tuple))
        
    # Outputs all entries in the log as tuple pairs without having to allocate one big string
    def dump(self, writer, since):
        first = True
        # TODO Iterating over self.data instead of self means that the entries are not in order
        #      There's a bug though, where iterating over self only returns a single log.
        for log in self.data:
            if log.time > since:
                if not first:
                    writer.write(",")
                first = False
                # TODO Not if this makes sense. Perhaps should write out each field explicitly
                #      It isn't quite correct json.
                writer.write(ujson.dumps(log))
        
    def __getitem__(self, index):
        return self.data[(index + self.end_index) % self.size_limit]
        
    def __len__(self):
        return len(self.data)