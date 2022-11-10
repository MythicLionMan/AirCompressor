from settings import Settings
from ringlog import RingLog

import time

EVENT_RUN=const(b'R')
EVENT_PURGE=const(b'P')

class EventLog(RingLog):
    def __init__(self, thread_safe = True):
        RingLog.__init__(self, "LLs", ["start", "stop", "event"], 40, thread_safe = thread_safe)
        self.console_log = False
        self.activity_open = False
            
    # Open a new log entry for the start time
    def log_start(self, event):
        with self.lock:
            start = time.time()
            # TODO Instead of + 1000000 this should just be int max, for the max possible time
            self.log((start, start + 100000000, event))
            self.activity_open = True
        
    # Update the current log entry with the current time
    def log_stop(self):
        with self.lock:
            if self.activity_open:
                # Grab the most recent log (for the open activity)
                current_log = self[0]
                
                # Extract the log properties
                event = current_log[2]
                start = current_log[0]
                
                stop = time.time()
                
                # Update the log with the current time as the stop time
                self[0] = (start, stop, event)
                self.activity_open = False
            
    def calculate_duty(self, duration):
        now = time.time()
        # Clamp the start of the sample window to 0
        if now > duration:
            query_start = now - duration
        else:
            query_start = now
        
        # Find the total time that the compressor was running in the window (query_start - now)
        with self.lock:            
            total_runtime = 0
            for i in range(len(self)):
                log = self[i]
                event = log[2]
                # Logs that are 'open' will have a stop time in the distant future. Logs that
                # end within the interval may have started before it began. Clamp the stop and
                # stop times to the query window.
                start = max(query_start, log[0])
                stop = min(now, log[1])
                #print("calculate_duty have log: start = %d stop = %d" % (start, stop))
                # Count the time for this event if this is a run event in the window from
                # (query_start - now). Since the start and stop times of the log have been
                # clamped to the query window this can be tested by checking to see if the
                # clamped interval is not empty.
                if event == EVENT_RUN and stop > start:
                    total_runtime += stop - start
            
            duty = total_runtime/duration
        
            # For debugging the duty calculations can be logged
            #print("Compressor has run for %d of the last %d seconds. Duty cycle is %f%%" % (total_runtime, duration, duty*100))
            
            # Return the percentage of the sample window where the compressor was running
            return duty
    
COMMAND_ON=const(b'O')
COMMAND_OFF=const(b'F')
COMMAND_RUN=const(b'R')
COMMAND_PAUSE=const(b'|')
COMMAND_PURGE=const(b'P')

class CommandLog(RingLog):
    def __init__(self, thread_safe):
        RingLog.__init__(self, "Ls", ["time", "command"], 10, thread_safe = thread_safe)
        self.console_log = False

    def log_command(self, event):
        self.log((time.time(), event))

class StateLog(RingLog):
    def __init__(self, settings, thread_safe):
        RingLog.__init__(self, "Lfff3s", ["time", "tank_pressure", "line_pressure", "duty", "state"], 200, thread_safe = thread_safe)
        self.last_log_time = 0
        self.settings = settings
        self.console_log = False
    
    def log_state(self, tank_pressure, line_pressure, duty, state):
        now = int(time.time())
        since_last = now - self.last_log_time
        #print("now = " + str(now) + " since last " + str(since_last) + " Interval " + str(self.settings.log_interval))
        if since_last > self.settings.log_interval:
            self.last_log_time = now
            self.log((now, tank_pressure, line_pressure, duty, state))
            
    @property
    def max_duration(self):
        return self.settings.log_interval * self.size_limit
