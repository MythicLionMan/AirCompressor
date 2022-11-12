from settings import Settings
from settings import ValueScale
from heartbeatmonitor import HeartbeatMonitor
import compressor_controller
import compressor_server
import compressor_ui

import time
import sys

import uasyncio as asyncio

# Default values for the persistent settings. These can be edited and saved.
default_settings = {
    # Compressor configuration
    "start_pressure": 90,
    "stop_pressure": 125,
    "min_line_pressure": 89,
    "max_duty": 0.6,
    "duty_duration": 10*60,
    "drain_duration": 10,
    "recovery_time": 3*60,
    "drain_delay": 5,
    "compressor_on_power_up": True,
    "auto_stop_time": 6*60*60,
    "log_interval": 10,
    
    # WiFi configuration
    "ssid": 'A Network',
    "wlan_password": '',
    "network_retry_timeout": 60*5,
    "dedicated_ip": '',
    "netmask": '',
    "gateway": '',
    "nameserver": '',

    # Sensor configuration
    "tank_pressure_sensor": {
        "value_min": 0,
        "value_max": 150,
        "sensor_min": 0,
        "sensor_max": 65535
    },
    "line_pressure_sensor": {
        "value_min": 0,
        "value_max": 150,
        "sensor_min": 0,
        "sensor_max": 65535
    },
    
    # Setting this to False will permanently de-activate the server for debugging
    # The following command can be used as a 'poison pill' to prevent the server
    # from booting up and taking control of the device when debugging:
    #
    #    curl "http://192.168.50.227/settings?activated=false"
    #
    # Restore control by manually editing 'settings.json' to remove the key.
    "activated": True
}

class CompressorSettings(Settings):
    # Static settings (cannot be updated or persisted)
    def __init__(self, default_settings):
        Settings.__init__(self, default_settings)
        
        self.tank_pressure_pin = 0   # ADC pin for pressure sensor
        self.line_pressure_pin = 1   # ADC pin for pressure sensor
        
        self.compressor_motor_pin = 15   # Output for compressor relay
        self.drain_solenoid_pin = 14     # Output for drain solenoid
        
        self.status_poll_interval = 250       # Update interval for status LEDs
        self.compressor_on_status_pin = "LED" # Output for power LED (turns on monitoring)
        self.compressor_on_status_pin2 = None # Secondary power LED output
        self.error_status_pin = 4             # Output for error LED
        self.compressor_motor_status_pin = 2  # Output for compressor motor status LED
        self.purge_status_pin = 3             # Output for purge solenoid status LED
        
        self.power_button_pin = 5             # Input for power button to toggle 'on' state
        self.run_pause_button_pin = 7         # Input for run/pause button to toggle motor state
        self.purge_button_pin = 8             # Input for purge button pin to activate purge cycle
        self.menu_button_pin = 9              # Input for menu button pin to select next menu
        self.value_up_button_pin = 10         # Input for value up button to increment selected value
        self.value_down_button_pin = 11       # Input for value down button to decrement selected value
        
        self.use_multiple_threads = True
        self.debug_mode = False

    def setup_properties(self, defaults):
        self.private_keys = ('wlan_password')
        self.values['tank_pressure_sensor'] = ValueScale(defaults['tank_pressure_sensor'])
        self.values['line_pressure_sensor'] = ValueScale(defaults['line_pressure_sensor'])
         
async def main():
    settings = CompressorSettings(default_settings)
    if not settings.activated:
        print('Settings has deactivated client. Aborting.')
        return
        
    # Run the compressor no matter what. It is essential that the compressor
    # pressure is monitored
    compressor = compressor_controller.CompressorController(settings, thread_safe = settings.use_multiple_threads)
    compressor.run()
            
    # Start any UI coroutines to monitor and update the main thread
    server = compressor_server.CompressorServer(compressor, settings)
    server.run()
    status = compressor_ui.LEDController(compressor, settings)
    status.run()
    pins = compressor_ui.CompressorPinMonitor(compressor, settings)
    pins.run()
    
    if settings.debug_mode:
        h = HeartbeatMonitor("coroutines", histogram_bin_width = 5)
        h.monitor_coroutines()
    
    try:
        # Loop forever while the coroutines process
        asyncio.get_event_loop().run_forever()
    finally:
        # Make sure that any background threads are terminated as well
        compressor.stop()
        server.stop()
        status.stop()
        pins.stop()
        print('Exception raised. Disabling background threads.')
        
    print("WARNING: Foreground coroutines are done.")

# Run main to start configuration
asyncio.run(main())

