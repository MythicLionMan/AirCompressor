import time
import sys
import machine
import uasyncio as asyncio

# A generic debounce coroutine that monitors multiple pins.
# Derived classes can overlaod pin_value_did_change to be notified
# when the state of a pin changes
class PinMonitor:
    # pin_ids: A dictionary that matches pin_names to pin_ids. The pins
    #          in the dictionary will be configured as inputs. When a pin
    #          changes state its name will be passed to pin_value_did_change
    def __init__(self, pin_ids, pull = machine.Pin.PULL_UP):
        # Map the pin ids to configured pin instances
        self.pins = { pin_name: machine.Pin(pin_id, machine.Pin.IN, pull) for (pin_name, pin_id) in pin_ids.items()}
        
    def pin_value_did_change(self, pin_name, new_value):
        pass
    
    async def _run(self, bounce_time, poll_interval):
        pins = self.pins
        # Get the initial pin states
        pin_values = { pin_name: pin.value() for (pin_name, pin) in pins.items() }
        # Create an array to hold the counter values
        pin_counters = { pin_name: 0 for pin_name in pins.keys() }
        
        self.running = True
        while self.running:
            for (pin_name, pin) in pins.items():
                # Read the current state of the pin
                value = pin.value()

                # If the pin value is different than the stored value increment the counter,
                # otherwise reset it
                pin_count = pin_counters[pin_name] + 1 if value != pin_values[pin_name] else 0
                
                if pin_count >= bounce_time:
                    # The pin has been stable at this new value for the bounce interval
                    # Switch the pin status and call the callback
                    pin_values[pin_name] = value
                    pin_counters[pin_name] = 0

                    self.pin_value_did_change(pin_name, value)
                else:
                    pin_counters[pin_name] = pin_count
                 
            await asyncio.sleep_ms(poll_interval)
                
    def run(self, bounce_time = 20, poll_interval = 1):
        self.run_task = asyncio.create_task(self._run(bounce_time, poll_interval))
        
    def stop(self):
        self.running = False
   