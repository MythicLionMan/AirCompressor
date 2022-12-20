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
#       - flashing when duty blocked
#    - purging_status
#       - shows status of purge valve
#       - on when open
#       - flashing when purge is pending
#    - error_status_pin
#       - shows pressure alerts and errors
#       - on when tank is underpressure
#       - flashing when there is a sensor error
#       - flashing when there is a pressure change error
class LEDController:
    def __init__(self, compressor, settings):
        self.settings = settings
        self.compressor = compressor
        
        self.compressor_on_status = machine.Pin(settings.compressor_on_status_pin, machine.Pin.OUT) if settings.compressor_on_status_pin is not None else None
        self.compressor_on_status2 = machine.Pin(settings.compressor_on_status_pin2, machine.Pin.OUT) if settings.compressor_on_status_pin2 is not None else None
            
        self.error_status = machine.Pin(settings.error_status_pin, machine.Pin.OUT) if settings.error_status_pin is not None else None

        self.motor_status = machine.Pin(settings.compressor_motor_status_pin, machine.Pin.OUT) if settings.compressor_motor_status_pin is not None else None
        self.purge_status = machine.Pin(settings.purge_status_pin, machine.Pin.OUT) if settings.purge_status_pin is not None else None
    
    def _update_pin(self, pin, on, flashing = False, flash_state = False):
        if pin is not None:
            pin.value((on and not flashing) or (flashing and flash_state))
    
    def _update_status(self):
        # Can do arithmetic directly on ticks_ms since we only need to determine the
        # 'parity' of the time. This bit will be low for half a second and high for
        # the next half.
        flash_time = True if int(time.ticks_ms()/500) & 1 else False
        
        state = self.compressor.state_dictionary
        
        compressor_on = state['compressor_on']
        
        purge_open = state['purge_open']
        purge_pending = state['purge_pending']
        
        motor_running = state['motor_state'] == compressor_controller.MOTOR_STATE_RUN
        motor_pending = state['run_request']
        
        pressure_error = state['tank_underpressure'] or state['line_underpressure']
        critical_error = state['tank_sensor_error'] or state['pressure_change_error']
                
        self._update_pin(self.compressor_on_status, compressor_on)
        self._update_pin(self.compressor_on_status2, compressor_on)
        self._update_pin(self.error_status, pressure_error, critical_error, flash_time)
        self._update_pin(self.motor_status, motor_running, motor_pending, flash_time)
        self._update_pin(self.purge_status, purge_open, purge_pending, flash_time)
    
    async def _run(self):
        self.running = True
        status_poll_interval = self.settings.status_poll_interval
        
        # Updating the status may take a different amount of time if other
        # coroutines block us. It isn't critical, but it's preferrable if
        # status updates occur at a fixed frequency (so that the leds flash
        # regularly). So instead of napping for the time between updates,
        # subtract the time that has elapsed since the last update was supposed
        # to happen
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
# Power button momentary: toggle run state
# Run/Pause button: toggle run state (if omitted will be combined with power button)
# Purge: Schedule a purge operation (if omitted will be combined with Value up button)
# Menu button: select next menu
# Menu button hold: select no menu and save
# Value up button: increase displayed value
# Value down button: decrease displayed value
# Value up button when not in menu: schedule a purge
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
        self.settings = settings
        self.menu_index = None
        self.did_change = False
        self.menu_timeout_task = None
        self.menu_timeout_time = None
        self.menus = [
            {'field': 'start_pressure', 'min': 80, 'max': 130, 'increment': self.settings.pressure_change_increment},
            {'field': 'stop_pressure', 'min': 80, 'max': 130, 'increment': self.settings.pressure_change_increment},
            {'field': 'max_duty', 'min': 0, 'max': 1, 'increment': self.settings.duty_change_increment},
        ]
        
    def pin_value_did_change(self, pin_name, new_value, previous_duration):
        #print('Pin {} changed value to {} after {} millis at old value'.format(pin_name, new_value, previous_duration))
        
        if not new_value:
            if pin_name == 'power':
                asyncio.create_task(self._power_down())
            elif pin_name == 'run_pause':
                print('Toggling run state')
                self.compressor.toggle_run_state()
            elif pin_name == 'purge':
                print('Requesting purge')
                self.compressor.purge()
            elif pin_name == 'menu':
                asyncio.create_task(self._next_menu())
            elif pin_name == 'value_up':
                self._value_up()
            elif pin_name == 'value_down':
                self._value_down()
            
        self._reset_menu_timeout()
            
    # Starts a timer waiting for any UI button to be pressed.
    def _reset_menu_timeout(self):
        self.menu_timeout_time = time.time() + self.settings.menu_timeout
        if self.menu_timeout_task is None:
            self.menu_timeout_task = asyncio.create_task(self._timeout_menu())

    # Waits for the UI button timeout and then calls _clear_menu_and_save
    # If canceled it does nothing, because presumably the caller has
    # performed the cleanup
    async def _timeout_menu(self):
        try:
            while True:
                remaining_time = self.menu_timeout_time - time.time()
                if remaining_time >= 0:
                    await asyncio.sleep(remaining_time)
                else:
                    break
            
            print('Menu timeout')
            self.menu_timeout_task = None
            self._clear_menu_and_save()
        except asyncio.CancelledError:
            print('Menu timeout cancelled')
            pass
        
    async def _power_down(self):
        try:
            await self.await_pin('power', self.settings.button_long_press)
            # Button was released before timeout. Short press.
            if 'run_pause' not in self.pin_ids:
                # There is no dedicated 'run_pause' pin, so toggle the run state
                print('Short press power button. Toggling run state')
                self.compressor.toggle_run_state()
        except asyncio.TimeoutError:
            # Timeout was reached without the pin changing state again,
            # so the button was held long enough to trigger a toggle
            print('Long press power button. Toggling on state')
            self.compressor.toggle_on_state()
                        
    def _clear_menu_and_save(self):
        print('Clearing menu, back to status')
        # Cancel any menu timeout
        if self.menu_timeout_task:
            self.menu_timeout_task.cancel()
            self.menu_timeout_task = None
            
        # The timeout has elapsed without another UI button being
        # pressed. Reset to the main menu
        self.menu_index = None

        # Save any updated prefs
        if self.did_change:
            print('Saved updated settings')
            self.settings.write_delta()
            self.did_change = False

    async def _next_menu(self):
        try:
            await self.await_pin('menu', self.settings.button_long_press)
            # Button was released before timeout. Short press.
            print('Short press menu button.')
            if self.menu_index == None:
                self.menu_index = 0
            else:
                self.menu_index = self.menu_index + 1
                
            if self.menu_index >= len(self.menus):
                self._clear_menu_and_save()
            else:
                field = self.menus[self.menu_index]['field']
                print('Selected menu {} with value {}'.format(field, self.settings[field]))
        except asyncio.TimeoutError:
            # Timeout was reached without the pin changing state again,
            # so the button was held long enough to jump home
            print('Long press menu btton.')
            self._clear_menu_and_save()
    
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
        if self.menu_index is None and 'purge' not in self.pin_ids:
            print('No active menu. Requesting purge()')
            self.compressor.purge()
        else:
            self.repeat_action_until('value_up', self._increment_menu_value, self.settings.min_key_repeat, self.settings.max_key_repeat, self.settings.key_repeat_ticks)

    def _value_down(self):
            self.repeat_action_until('value_down', self._decrement_menu_value, self.settings.min_key_repeat, self.settings.max_key_repeat, self.settings.key_repeat_ticks)

    def _increment_menu_value(self):
        if 'value_down' not in self.pin_ids:
            # There is no 'value_down' pin, so cycle the value back to min when max is reached
            def increment_cycle(menu, value):
                new_value = value + menu['increment']
                return menu['min'] if new_value > menu['max'] else new_value
            
            self._update_field(increment_cycle)
        else:
            self._update_field(lambda menu, value: min(value + menu['increment'], menu['max']))
            
        self._reset_menu_timeout()
            
    def _decrement_menu_value(self):
        self._update_field(lambda menu, value: max(value - menu['increment'], menu['min']))
        self._reset_menu_timeout()
    
    @property
    def current_menu(self):
        if self.menu_index is not None:
            return self.menus[self.menu_index]
        return None
