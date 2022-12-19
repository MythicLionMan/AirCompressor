from settings import Settings
from settings import ValueScale
import debug
from heartbeatmonitor import HeartbeatMonitor
import compressor_controller
try:
    import compressor_server
    server_enabled = True
except ImportError:
    server_enabled = False
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
    "recovery_time": 3*60,
    "drain_duration": 10,
    "drain_delay": 5,
    "unload_duration": 20,
    "compressor_on_power_up": True,
    "auto_stop_time": 6*60*60,
    "log_interval": 10,
    
    "pressure_change_duration": 6,              # Number of seconds to wait for a pressure change before disabling motor
    "detect_pressure_change_threshold": 0.35,   # The change in PSI/s required to determine that the motor is running properly
    
    # WiFi configuration
    "ssid": 'A Network',
    "wlan_password": '',
    "network_retry_timeout": 60*5,
    "dedicated_ip": '',
    "netmask": '',
    "gateway": '',
    "nameserver": '',
    
    # UI configuration
    "button_long_press": 500,          # Duration of a 'long' button press
    "menu_timeout": 15,                # Timeout before automatically leaving menu and saving
    "min_key_repeat": 100,             # Minimum key repeat interval
    "max_key_repeat": 500,             # Maximum key repeat interval
    "key_repeat_ticks": 10,            # Number of key repeat ticks to transition from max interval to min
    
    # Sensor configuration
    "tank_pressure_sensor": {
        "value_min": 0,
        "value_max": 150,
        "sensor_min": 6554,            # 0.5V from sensor scaled to 0.33V for Pico (10%)
        "sensor_max": 58981            # 4.5V from sensor scaled to 2.97V for Pico (90%)
    },
    "line_pressure_sensor": {
        "value_min": 0,
        "value_max": 150,
        "sensor_min": 6554,            # 0.5V from sensor scaled to 0.33V for Pico (10%)
        "sensor_max": 58981            # 4.5V from sensor scaled to 2.97V for Pico (90%)
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
        
        self.tank_pressure_pin = 0       # ADC pin for pressure sensor
        self.line_pressure_pin = None    # ADC pin for pressure sensor
        
        self.compressor_motor_pin = 15   # Output for compressor relay
        self.unload_solenoid_pin = 14    # Output for unload solenoid
        self.drain_solenoid_pin = 16     # Output for drain solenoid
        
        self.status_poll_interval = 250       # Update interval for status LEDs
        self.compressor_on_status_pin = 2     # Output for power LED (indicates that pressure is being regulated)
        self.compressor_on_status_pin2 = 25   # Output for secondary power LED
        self.error_status_pin = 5             # Output for error LED
        self.compressor_motor_status_pin = 4  # Output for compressor motor status LED
        self.purge_status_pin = 3             # Output for purge solenoid status LED
        
        self.pressure_change_increment = 1    # The amount to adjust pressure by when increment/decrement button is pressed
        self.duty_change_increment = 0.01     # The amount to adjust duty by when increment/decrement button is pushed
        self.power_button_pin = 10            # Input for power button to toggle 'on' state
        self.run_pause_button_pin = None      # Input for run/pause button to toggle motor state
        self.purge_button_pin = None          # Input for purge button pin to activate purge cycle
        self.menu_button_pin = 11             # Input for menu button pin to select next menu
        self.value_up_button_pin = 12         # Input for value up button to increment selected value
        self.value_down_button_pin = 13       # Input for value down button to decrement selected value
        
        self.http_root = 'http/'
        self.watchdog_timeout = 5000;         # Milliseconds to allow between updates before the system is restarted
        
        self.use_multiple_threads = False
        #self.debug_mode = debug.DEBUG_COROUTINES | debug.DEBUG_WEB_REQUEST | debug.DEBUG_ADC_SIMULATE #| debug.DEBUG_ADC
        self.debug_mode = debug.DEBUG_NONE

    def setup_properties(self, defaults):
        self.private_keys = ('wlan_password')
        self.values['tank_pressure_sensor'] = ValueScale(defaults['tank_pressure_sensor'])
        self.values['line_pressure_sensor'] = ValueScale(defaults['line_pressure_sensor'])
         
async def main():
    settings = CompressorSettings(default_settings)
    if not settings.activated:
        print('Settings has deactivated client. Aborting.')
        return
    
    tasks = []
    
    # Run the compressor no matter what. It is essential that the compressor
    # pressure is monitored
    compressor = compressor_controller.CompressorController(settings, thread_safe = settings.use_multiple_threads)
    tasks.append(compressor)
            
    # Start any UI coroutines to monitor and update the main thread
    if server_enabled:
        tasks.append(compressor_server.CompressorServer(compressor, settings))
    tasks.append(compressor_ui.LEDController(compressor, settings))
    tasks.append(compressor_ui.CompressorPinMonitor(compressor, settings))
    
    if settings.debug_mode & debug.DEBUG_COROUTINES:
        tasks.append(HeartbeatMonitor("coroutines", histogram_bin_width = 5))
    
    # Run all of the tasks
    [task.run() for task in tasks]
        
    try:
        # Loop forever while the coroutines process
        asyncio.get_event_loop().run_forever()
    finally:
        # Make sure that any background threads are terminated as well
        [task.stop() for task in tasks]
        
    print("WARNING: Foreground coroutines are done.")

# Run main to start configuration
asyncio.run(main())
