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
#
# Power button hold: toggle on state
# Run/Pause button: toggle run state
# Menu button: select next menu
# Value up button: increase displayed value
# Value down button: decrease displayed value
class CompressorPinMonitor(pin_monitor.PinMonitor):
    def __init__(self, compressor, settings):
        pin_monitor.PinMonitor.__init__(self, {
            'power': settings.power_button_pin,
            'run_pause': settings.run_pause_button_pin,
            'purge': settings.purge_button_pin,
            'menu': settings.menu_button_pin,
            'value_up': settings.value_up_button_pin,
            'value_down': settings.value_down_button_pin
        })
        self.compressor = compressor
        self.menu_index = None
        self.did_change = False
        self.menu_timeout = None
        self.menus = [
            {'field': 'start_pressure', 'min': 80, 'max': 130, 'increment': 5},
            {'field': 'stop_pressure', 'min': 80, 'max': 130, 'increment': 5},
            {'field': 'max_duty', 'min': 0, 'max': 1, 'increment': 0.05},
        ]
        
    def pin_value_did_change(self, pin_name, new_value, previous_duration):
        print('Pin {} changed value to {} after {} millis at old value'.format(pin_name, new_value, previous_duration))
        
        if new_value:
            if pin_name == 'power':
                self.run_task = asyncio.create_task(self._handle_power_down())
            elif pin_name == 'run_pause':
                print('Toggling run state')
                self.compressor.toggle_run_state()
            elif pin_name == 'purge':
                print('Requesting purge')
                self.compressor.purge()
            elif pin_name == 'menu':
                self._next_menu()
                self._handle_ui_down()
            elif pin_name == 'value_up':
                self._value_up()
                self._handle_ui_down()
            elif pin_name == 'value_down':
                self._value_down()
                self._handle_ui_down()
            
    async def _handle_power_down(self):
        try:
            await asyncio.await_for_ms(self.pins['power'].event, 500)
        except asyncio.TimeoutError:
            print('Toggling on state')
            # Timeout was reached without the pin changing state again,
            # so the button was held long enough to trigger a toggle
            self.compressor.toggle_on_state()
            
    # Starts a timer waiting for any UI button to be pressed.
    # I used to have a neat async version of this, but I couldn't
    # figure out how to wait on multiple events at once, but return
    # when any of them fired.
    async def _handle_ui_down(self):
        self.menu_timeout = time.time() + 15

    # If the UI button timeout has expried then no button has been
    # pressed for a while, so reset the menu to the default. If there
    # are any settings changes to save they will be persisted at this
    # time.
    def derived_update(self):
        if self.menu_timeout and time.time() >= self.menu_timeout:
            # Cancel the timeout until a UI button is pressed again
            self.menu_timeout = None
            
            # The timeout has elapsed without another UI button being
            # pressed. Reset to the main menu
            self.menu_index = None

            # Save any updated prefs
            if self.did_change:
                print('Saved updated settings')
                self.settings.write_delta()
                self.did_change = False

    def _next_menu(self):
        if self.menu_index == None:
            self.menu_index = 0
        else:
            self.menu_index = self.menu_index + 1
            
        if self.menu_index >= len(self.menus):
            self.menu_index = None
    
    def _update_field(self, update_lambda):
        menu = self.current_menu;
        if menu is not None:
            value = self.settings[menu['field']]
            new_value = update_lambda(menu, value)
            if value != new_value:
                self.settings.update({ menu['field'] : new_value })
                print('Updated {} to {}'.format(menu['field'], new_value))
                self.did_change = True
        
    def _value_up(self):
        self._update_field(lambda menu, value: min(value + menu['increment'], menu['max']))
    
    def _value_down(self):
        self._update_field(lambda menu, value: max(value - menu['increment'], menu['min']))
    
    @property
    def current_menu(self):
        if self.menu_index is not None:
            return self.menus[self.menu_index]
        return None
