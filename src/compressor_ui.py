import compressor_controller
import pin_monitor

import time
import machine
import uasyncio as asyncio

# Updates the status leds. The LEDs are configured to mimic those in the web client
# and apps, but there are some difference due to not having a pin colour and not
# having to show connection errors.
#
# The status led values are:
#    - compressor_on_status_pin
#       - power is on/off to the compressor
#    - compressor_on_status_pin2
#       - same as the above. Lets an external and onboard pin share config
#    - compressor_motor_status_pin
#       - shows motor status
#       - on when running
#       - flashing when pending
#    - purging_status
#       - shows status of purge valve
#       - on when open
#       - flashing when purge is pending
#    - error_status_pin
#       - shows pressure alerts and errors
#       - on when tank is underpressure
#       - flashing when underpressure and duty blocked
#       - flashing when there is a sensor error
class LEDController:
    def __init__(self, compressor, settings):
        self.settings = settings
        self.compressor = compressor
        
        self.compressor_on_status = machine.Pin(settings.compressor_on_status_pin, machine.Pin.OUT)
        if settings.compressor_on_status_pin2 is not None:
            self.compressor_on_status2 = machine.Pin(settings.compressor_on_status_pin2, machine.Pin.OUT)
        else:
            self.compressor_on_status2 = None
            
        self.error_status = machine.Pin(settings.error_status_pin, machine.Pin.OUT)

        self.motor_status = machine.Pin(settings.compressor_motor_status_pin, machine.Pin.OUT)
        self.purge_status = machine.Pin(settings.purge_status_pin, machine.Pin.OUT)
    
    def _update_pin(self, pin, on, flashing = False, flash_state = False):
        if pin is not None:
            pin.value((on and not flashing) or (flashing and flash_state))
    
    def _update_status(self):
        # Can do arithmetic directly on ticks_ms since we only need to determine the
        # 'parity' of the time. This bit will be low for half a second and high for
        # the next half.
        flash_time = True if int(time.ticks_ms()/500) & 1 else False
        
        state = self.compressor.state_dictionary
        motor_state = state['motor_state']
        motor_running = motor_state == compressor_controller.MOTOR_STATE_RUN

        has_error = state['tank_underpressure'] or state['line_underpressure']

        # Duty errors only matter when the tank is underpressure
        duty_error = motor_state == compressor_controller.MOTOR_STATE_DUTY and state['tank_underpressure']
        error_flash = duty_error or state['tank_sensor_error']
                
        self._update_pin(self.compressor_on_status, state['compressor_on'])
        self._update_pin(self.compressor_on_status2, state['compressor_on'])
        self._update_pin(self.error_status, has_error, error_flash, flash_time)
        self._update_pin(self.motor_status, motor_running, state['run_request'], flash_time)
        self._update_pin(self.purge_status, state['purge_open'], state['purge_pending'], flash_time)
    
    async def _run(self):
        self.running = True
        status_poll_interval = self.settings.status_poll_interval
        
        # Updating the status may take a different amount of time if other
        # coroutines block us. It isn't critical, but it's preferrable if
        # status updates occur at a fixed frequency (so that the leds flash
        # regularly). So instead of napping for the time between updates 
        next_update_time = time.ticks_add(time.ticks_ms(), status_poll_interval)
        while self.running:
            self._update_status()
            
            # Sleep until the next update time
            nap_time = time.ticks_diff(next_update_time, time.ticks_ms())
            if nap_time > 0:
                await asyncio.sleep_ms(nap_time)
                
            # Schdule the next update in the future. In case we're 'running behind'
            # calculate the number of intervals that have elapsed since the last update
            ellapsed_intervals = int(time.ticks_diff(time.ticks_ms(), next_update_time)/status_poll_interval) + 1
            next_update_time = time.ticks_add(next_update_time, status_poll_interval*ellapsed_intervals)

    def run(self):
        self.run_task = asyncio.create_task(self._run())
        
    def stop(self):
        self.running = False
        
# Monitors pins connected to buttons and handles the responses
class CompressorPinMonitor(pin_monitor.PinMonitor):
    def __init__(self, compressor, settings):
        pin_monitor.PinMonitor.__init__(self, { 'power': settings.power_button_pin })
        self.compressor = compressor
        
    def pin_value_did_change(self, pin_name, new_value, previous_duration):
        print('Pin {} changed value to {} after {} millis at old value'.format(pin_name, new_value, previous_duration))
        
        if pin_name == 'power' and new_value:
            self.compressor.toggle_on_state()
