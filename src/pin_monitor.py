import time
import sys
import math
import machine
import uasyncio as asyncio

# A generic debounce coroutine that monitors multiple pins.
# Derived classes can overlaod pin_value_did_change to be notified
# when the state of a pin changes
class PinMonitor:
    # pin_ids: A dictionary that matches pin_names to pin_ids. The pins
    #          in the dictionary will be configured as inputs. When a pin
    #          changes state its name will be passed to pin_value_did_change.
    #          If any pin_id is None then the pin will not be configured.
    def __init__(self, pin_ids, pull = machine.Pin.PULL_UP):
        # Filter out any pins that have no id
        self.pin_ids = {pin_name:pin_id for pin_name,pin_id in pin_ids.items() if pin_id is not None}
        self.pull = pull
        
    def pin_value_did_change(self, pin_name, pin_state, new_value, previous_duration):
        pass
        
    # Repeats a function until a pin changes state. The repeat interval will start long
    # and decrease with each repeat.
    def repeat_action_until(self, pin_state, action, min_time = 100, max_time = 1000, ramp_ticks = 10):
        asyncio.create_task(self._repeat_action_until(pin_state, action, min_time, max_time, ramp_ticks))
        
    async def _repeat_action_until(self, pin_state, action, min_time, max_time, ramp_ticks):
        i = 0
        event = pin_state.event
        time_range = max_time - min_time
        # A sigmoid function that will be close to 1 when i = 0 and close to 0
        # when i = ramp_ticks. This will ramp the button interval down smoothly
        sigmoid = lambda i, ramp_ticks: 0.5 - math.atan((i - ramp_ticks/2)*7.5/ramp_ticks)/math.pi        
        while True:
            try:
                # Fire the action
                action()
                
                delay = int(min_time + time_range * sigmoid(i, ramp_ticks))
                i = i + 1
                # Delay until either the event is triggered or the delay times out
                await asyncio.wait_for_ms(event.wait(), delay)
                # The pin has changed state, so the repeat is over
                return
            except asyncio.TimeoutError:
                # A timeout without a pin state change means the button is still down
                pass
    
    async def _run(self, bounce_time, poll_interval):
        # Map the pin ids to configured pin instances
        pins = { pin_name: PinState(pin_id, self.pull) for (pin_name, pin_id) in self.pin_ids.items()}
        
        self.running = True
        while self.running:
            try:
                for (pin_name, pin_state) in pins.items():
                    value = pin_state.update(bounce_time)
                    if value is not None:
                        self.pin_value_did_change(pin_name, pin_state, value[0], value[1])
                     
                await asyncio.sleep_ms(poll_interval)
            except Exception as e:
                print("Error processing pin change.")
                sys.print_exception(e)
                
    def run(self, bounce_time = 20, poll_interval = 1):
        self.run_task = asyncio.create_task(self._run(bounce_time, poll_interval))
        
    def stop(self):
        self.running = False
        
class PinState:
    def __init__(self, pin_id, pull):
        self.pin = machine.Pin(pin_id, machine.Pin.IN, pull)
        self.value = self.pin.value()
        self.counter = 0
        self.previous_state_change_time = time.ticks_ms()
        self.event = asyncio.Event()
        
    def update(self, bounce_time):
        # Read the current state of the pin
        current_value = self.pin.value()

        # If the current value is different than the stored value increment the counter,
        # otherwise reset it
        pin_count = self.counter + 1 if current_value != self.value else 0
        
        if pin_count >= bounce_time:
            # The pin has been stable at this new value for the bounce interval
            # Switch the pin status and call the callback
            self.value = current_value
            self.counter = 0
            
            now = time.ticks_ms()
            previous_duration = time.ticks_diff(now, self.previous_state_change_time)
            self.previous_state_change_time = now
            self.event.set()
            self.event.clear()
            
            return (current_value, previous_duration)
        else:
            self.counter = pin_count

        return None
        
   
