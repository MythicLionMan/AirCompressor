import network
import socket
from settings import Settings
from settings import ValueScale
from server import Server
from server import flatten_dict
from ringlog import RingLog
from condlock import CondLock
from heartbeatmonitor import HeartbeatMonitor
from compressor_controller import CompressorController

import compressorlogs
from compressorlogs import EventLog
from compressorlogs import CommandLog
from compressorlogs import StateLog

import ujson
import time
import sys
import _thread

from machine import Pin
from machine import WDT
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
        self.compressor_motor_status_pin = "LED"
        self.compressor_active_status_pin = 2
        self.purge_active_status_pin = 3
        self.use_multiple_threads = True
        self.debug_mode = False

    def setup_properties(self, defaults):
        self.private_keys = ('wlan_password')
        self.values['tank_pressure_sensor'] = ValueScale(defaults['tank_pressure_sensor'])
        self.values['line_pressure_sensor'] = ValueScale(defaults['line_pressure_sensor'])

####################
# Network Functions
#

class CompressorServer(Server):
    def __init__(self, compressor, settings):
        Server.__init__(self, settings)
        self.compressor = compressor
        self.root_document = 'status.html'
    
    # Overloads the base class method to supply state and settings values
    # as substitutions for html documents. Other documents do not get
    # substitutions
    async def return_http_document(self, writer, path):
        if path.endswith('.html'):
            values = {}
            values.update(self.compressor.state_dictionary)
            values.update(self.settings.public_values_dictionary)

            values = flatten_dict(values);
        else:
            values = None
        
        await super().return_http_document(writer, path = path, substitutions = values)

    def return_ok(self, writer):
        self.return_json(writer, {'result':'ok'})
    
    async def serve_client(self, reader, writer):
        try:
            request_line = await reader.readline()

            # TODO Don't log every endpoint, only log serving pages (every endpoint gets chatty)
            headers = await self.read_headers(reader)
            (request_type, endpoint, parameters) = self.parse_request(request_line)

            compressor = self.compressor
                
            if request_type == 'GET':
                if endpoint == '/settings':
                    if len(parameters) > 0:
                        try:
                            # settings are only updated from the main thread, so it is sufficient
                            # to rely on the individual locks in these two methods
                            self.settings.update(parameters)
                            self.settings.write_delta()
                            
                            self.return_json(writer, self.settings.public_values_dictioniary)
                        except KeyError as e:
                            self.return_json(writer, {'result':'unknown key error', 'missing key': e}, 400)                    
                    else:
                        self.return_json(writer, self.settings.public_values_dictioniary)
                
                # The rest of the commands only accept 0 - 2 parameters
                elif len(parameters) > 2:                
                    self.return_json(writer, {'result':'unexpected parameters'}, 400)                        
                elif endpoint == '/purge':
                    drain_duration = parameters.get("drain_duration", None)
                    if drain_duration:
                        drain_duration = int(drain_duration)

                    drain_delay = parameters.get("drain_delay", None)
                    if drain_delay:
                        drain_delay = int(drain_delay)

                    compressor.purge(drain_duration, drain_delay)
                    self.return_ok(writer)
                
                # The rest of the commands only accept 0 or 1 parameters
                elif len(parameters) > 1:
                    self.return_json(writer, {'result':'unexpected parameters'}, 400)                        
                elif endpoint == '/activity_logs':
                    # Return all state logs since a value supplied by the caller (or all logs if there is no since)
                    self.response_header(writer)
                    writer.write('{"time":' + str(time.time()) + ',"activity":[')
                    # The logs need to be locked so that they can be accessed. To prevent holding the lock
                    # for too long (which could block the compressor thread), the dump commands set blocking
                    # to False. But this will require the buffer to hold all of the data that is being sent,
                    # so it is a memory consumption risk.
                    
                    # Return all activity logs that end after since
                    await compressor.activity_log.dump(writer, int(parameters.get('since', 0)), 1, blocking = not compressor.thread_safe)
                    writer.write('],"commands":[')
                    # Return all command logs that fired after since
                    await compressor.command_log.dump(writer, int(parameters.get('since', 0)), blocking = not compressor.thread_safe)
                    writer.write(']}')
                elif endpoint == '/state_logs':
                    # Return all state logs since a value supplied by the caller (or all logs if there is no since)
                    self.response_header(writer)
                    # The logs need to be locked so that they can be accessed. To prevent holding the lock
                    # for too long (which could block the compressor thread), the dump commands set blocking
                    # to False. But this will require the buffer to hold all of the data that is being sent,
                    # so it is a memory consumption risk.
                    writer.write('{"time":' + str(time.time()) + ',"maxDuration":' + str(compressor.state_log.max_duration) + ',"state":[')
                    await compressor.state_log.dump(writer, int(parameters.get('since', 0)), blocking = not compressor.thread_safe)
                    writer.write(']}')
                elif endpoint == '/on':
                    shutdown_time = parameters.get("shutdown_in", None)
                    if shutdown_time:
                        shutdown_time = int(shutdown_time)
                        
                    compressor.compressor_on(shutdown_time)
                    self.return_ok(writer)

                # The rest of the commands do not accept parameters
                elif len(parameters) > 0:
                    self.return_json(writer, {'result':'unexpected parameters'}, 400)
                elif endpoint == '/':
                    await self.return_http_document(writer, self.root_document)
                elif endpoint == '/status':
                    self.return_json(writer, compressor.state_dictionary)
                elif endpoint == '/run':
                    compressor.request_run()
                    self.return_ok(writer)
                elif endpoint == '/off':
                    compressor.compressor_off()
                    self.return_ok(writer)
                elif endpoint == '/pause':
                    compressor.pause()
                    self.return_ok(writer)
                else:
                    # Not an API endpoint, try to serve the requested document
                    # TODO Need to strip the leading '/' off of the endpoint to get the path
                    await self.return_http_document(writer, endpoint)
            elif request_type == 'POST':
                if len(parameters) > 0:
                    self.return_json(writer, {'result':'unexpected parameters'}, 400)                
                elif endpoint == '/settings' and headers['Content-Type'] == 'application/json':
                    content_length = int(headers['Content-Length'])                    
                    raw_data = await reader.read(content_length)
                    parameters = ujson.loads(raw_data)

                    try:
                        # settings are only updated from the main thread, so it is sufficient
                        # to rely on the individual locks in these two methods
                        self.settings.update(parameters)
                        self.settings.write_delta()
                        
                        self.return_ok(writer)
                    except KeyError as e:
                        self.return_json(writer, {'result':'unknown key error', 'missing key': e}, 400)                        
                else:
                    self.return_json(writer, {'result':'unknown endpoint'}, 404)
            else:
                self.return_json(writer, {'result':'unknown method'}, 404)
        except Exception as e:
            print("Error handling request.")
            sys.print_exception(e)
        finally:
            await writer.drain()
            await writer.wait_closed()
                
#######################
# Main

async def main():
    settings = CompressorSettings(default_settings)
    # Run the compressor no matter what. It is essential that the compressor
    # pressure is monitored
    compressor = CompressorController(settings, thread_safe = settings.use_multiple_threads)
    compressor.run()
            
    # Start any UI coroutines to monitor and update the main thread
    server = CompressorServer(compressor, settings)
    server.run()
    
    if settings.debug_mode:
        h = HeartbeatMonitor("coroutines", histogram_bin_width = 5)
        h.monitor_coroutines()
    
    try:
        # Loop forever while the coroutines process
        asyncio.get_event_loop().run_forever()
    finally:
        # Make sure that any background thread are terminated as well
        compressor.running = False
        server.stop()
        print('Exception raised. Disabling background threads.')
        
    print("WARNING: Foreground coroutines are done.")

# Run main to start configuration
asyncio.run(main())

