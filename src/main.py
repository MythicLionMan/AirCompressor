from settings import Settings
from settings import ValueScale
from heartbeatmonitor import HeartbeatMonitor
import compressor_controller
import compressor_server
import led_controller

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
    }
}

class CompressorSettings(Settings):
    # Static settings (cannot be updated or persisted)
    def __init__(self, default_settings):
        Settings.__init__(self, default_settings)
        
        self.tank_pressure_pin = 0
        self.line_pressure_pin = 1
        
        self.compressor_motor_pin = 15
        self.drain_solenoid_pin = 14
        
        self.status_poll_interval = 250
        self.compressor_on_status_pin = "LED"
        self.compressor_on_status_pin2 = None
        self.error_status_pin = 4
        self.compressor_motor_status_pin = 2
        self.purge_status_pin = 3
        
        self.use_multiple_threads = True
        self.debug_mode = False

    def setup_properties(self, defaults):
        self.private_keys = ('wlan_password')
        self.values['tank_pressure_sensor'] = ValueScale(defaults['tank_pressure_sensor'])
        self.values['line_pressure_sensor'] = ValueScale(defaults['line_pressure_sensor'])
            
async def main():
    settings = CompressorSettings(default_settings)
    # Run the compressor no matter what. It is essential that the compressor
    # pressure is monitored
    compressor = compressor_controller.CompressorController(settings, thread_safe = settings.use_multiple_threads)
    compressor.run()
            
    # Start any UI coroutines to monitor and update the main thread
    server = compressor_server.CompressorServer(compressor, settings)
    server.run()
    status = led_controller.LEDController(compressor, settings)
    status.run()
    
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
        print('Exception raised. Disabling background threads.')
        
    print("WARNING: Foreground coroutines are done.")

# Run main to start configuration
asyncio.run(main())

