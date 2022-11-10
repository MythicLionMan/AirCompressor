import time
import uasyncio as asyncio
import gc

# A utility that can be used to time the regularity of a task event loop,
# or of the coroutine event loop.
# For timing couroutines call monitor_coroutines() and it will report on how
# regularly all of the other coroutines yield control to it. For timing
# coroutines only a single monitor is needed, and any polling interval
# can be used.
#
# For timing tasks initialize the interval to the update interval of the task
# and call update() each time through the event loop of the task that you want
# to monitor:
#
#    h = HeartbeatMonitor('compressorLoop', poll_interval)
#      
#    while self.running:
#        h.update()
#        do_work()
#        time.sleep(poll_interval)
class HeartbeatMonitor:
    def __init__(self, name, interval = 1, log_interval = 10, memory_debug = False, histogram_bins = 10, histogram_bin_width = 10):
        self.name = name
        self.interval = interval
        self.log_interval = log_interval
        self.memory_debug = memory_debug
        
        self.prev_millis = 0
        self.min_variance = 1000000000
        self.max_variance = 0
        self.variance_tally = 0
        self.variance_count = 0
        self.histogram_bin_width = histogram_bin_width
        self.histogram = [0 for i in range(histogram_bins)] 
        
    def monitor_coroutines(self):
        asyncio.create_task(self.coroutine_monitor())

    async def coroutine_monitor(self):
        while True:
            self.update()
            await asyncio.sleep(self.interval)
            
    def update(self):        
        millis = time.ticks_ms()
        variance = time.ticks_diff(millis, self.prev_millis) - self.interval*1000
        if self.prev_millis != 0:
            self.max_variance = max(self.max_variance, variance)
            self.min_variance = min(self.min_variance, variance)
            self.variance_tally = self.variance_tally + variance
            self.variance_count = self.variance_count + 1
            bin_number = min(max(0, int(variance/self.histogram_bin_width)), len(self.histogram) - 1)
            self.histogram[bin_number] = self.histogram[bin_number] + 1
                  
            if self.log_interval == 0 or self.variance_count % self.log_interval == 0:
                print("Hearbeat {}[{}]: variance min {} max {} avg {:.2f} histogram [{}]".format(
                    self.name,
                    self.variance_count,
                    self.min_variance,
                    self.max_variance,
                    self.variance_tally/self.variance_count,
                    '|'.join(map(str, self.histogram))
                ))
                
                if self.memory_debug:
                    gc.collect()
                    print('{} Allocated = {} free = {}'.format(time.time(), gc.mem_alloc(), gc.mem_free()))

        self.prev_millis = millis