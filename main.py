#import network

import ujson
import time

from machine import Pin
from machine import WDT
import uasyncio as asyncio
from ucollections import namedtuple

# Default values for the persistent settings. These can be edited and saved.
default_settings = {
    # Compressor configuration
    "start_pressure": 90,
    "stop_pressure": 125,
    "max_duty": 0.6,
    "duty_duration": 10*60,
    "drain_duration": 10,
    "drain_delay": 5,
    "compressor_on_power_up": True,
    "auto_stop_time": 6*60*60,
    "log_interval": 10,
    
    # WiFi configuration
    "ssid": 'Wokwi-GUEST',
    "wlan_password": '',
    "network_retry_timeout": 60*5,
    
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

# Static settings
tank_pressure_pin = const(0)
line_pressure_pin = const(1)
compressor_motor_pin = const(15)
drain_solenoid_pin = const(14)

# HTML Templates

html_status = """<!DOCTYPE html>
<html>
    <head><title>Air Compressor</title></head>
    <body><h1>Air Compressor</h1>
    <table>
        <tr><td>Start Pressure</td><td>$start_pressure$</td></tr>
        <tr><td>Stop Pressure</td><td>$stop_pressure$</td></tr>
        <tr><td>Max Duty</td><td>$max_duty$</td></tr>
        <tr><td>Duty Duration</td><td>$duty_duration$</td></tr>
        <tr><td>Drain Duration</td><td>$drain_duration$</td></tr>
        <tr><td>Drain Delay</td><td>$drain_delay$</td></tr>
        <tr><td>Compressor On Power Up</td><td>$compressor_on_power_up$</td></tr>
        <tr><td>Auto Stop Time</td><td>$auto_stop_time$</td></tr>
        <tr><td>Log Interval</td><td>$log_interval$</td></tr>
    </table>
    <p>$$</p>
    </body>
</html>
"""

###################
# Settings

class ValueScale:
    def __init__(self, defaults):
        self.defaults = defaults
        self.update(defaults)
        
    def map(self, raw_value):
        if raw_value < self.sensor_min or raw_value > self.sensor_max:
            return None
            
        scaled = (raw_value - self.sensor_min)/self.sensor_range
        return scaled*self.value_range + self.value_min
        
    @property
    def dictionary_representation(self):
        return {
            "value_min": self.value_min,
            "value_max": self.value_max,
            "sensor_min": self.sensor_min,
            "sensor_max": self.sensor_max
        }
        
    # Updates the values of self using a dictionary, and returns the values that are
    # not the same as the defaults
    def update(self, values):
        delta = {}
        defaults = self.defaults
        
        for key, value in values.items():
            if not defaults[key] == values[key]:
                delta[key] = value
                
            if key == "value_min":
                self.value_min = float(value)
            elif key == "value_max":
                self.value_max = float(value)
            elif key == "sensor_min":
                self.sensor_min = int(value)
            elif key == "sensor_max":
                self.sensor_max = int(value)
                    
        self.sensor_range = self.sensor_max - self.sensor_min
        self.value_range = self.value_max - self.value_min

        return delta
        
class Settings:
    def __init__(self, defaults):
        self.defaults = defaults
        self.persist_path = 'settings.json'
        
        # Create the ValueScale settings
        self.tank_pressure = ValueScale(defaults["tank_pressure_sensor"])
        self.line_pressure = ValueScale(defaults["line_pressure_sensor"])
                
        # Read the saved settings. This will populate all of the properties of self
        self._read()
        
    @property
    def dictionary_representation(self):
        return {
            "start_pressure": self.start_pressure,
            "stop_pressure": self.stop_pressure,
            "max_duty": self.max_duty,
            "duty_duration": self.duty_duration,
            "drain_duration": self.drain_duration,
            "drain_delay": self.drain_delay,
            "compressor_on_power_up": self.compressor_on_power_up,
            "auto_stop_time": self.auto_stop_time,
            "log_interval": self.log_interval,
            
            "ssid": self.ssid,
            "wlan_password": self.wlan_password,
            "network_retry_timeout": self.network_retry_timeout,
            
            "tank_pressure_sensor": self.tank_pressure.dictionary_representation,
            "line_pressure_sensor": self.line_pressure.dictionary_representation
        }
        
    # Updates the settings of self with values in a dictionary and writes the updated
    # values to permanent storage
    def update(self, values):
        delta = ujson.dumps(self._update(values))
        f = open(self.persist_path, 'w')
        f.write(delta)
        f.close()

    # Updates the values of self using a dictionary, and returns the values that are
    # not the same as the defaults
    def _update(self, values):
        delta = {}
        defaults = self.defaults
        
        for key, value in values.items():
            if key == "tank_pressure_sensor":
                delta[key] = self.tank_pressure.update(value)
            elif key == "line_pressure_sensor":
                delta[key] = self.line_pressure.update(value)
            else:
                if defaults[key] != values[key]:
                    delta[key] = value
                
                if key == "start_pressure":
                    self.start_pressure = int(value)
                elif key == "stop_pressure":
                    self.stop_pressure = int(value)
                elif key == "max_duty":
                    self.max_duty = float(value)
                elif key == "duty_duration":
                    self.duty_duration = int(value)
                elif key == "drain_duration":
                    self.drain_duration = int(value)
                elif key == "drain_delay":
                    self.drain_delay = int(value)
                    
                elif key == "compressor_on_power_up":
                    self.compressor_on_power_up = bool(value)
                elif key == "auto_stop_time":
                    self.auto_stop_time = int(value)
                    
                elif key == "log_interval":
                    self.log_interval = int(value)
                    
                elif key == "ssid":
                    self.ssid = value
                elif key == "wlan_password":
                    self.wlan_password = value
                elif key == "network_retry_timeout":
                    self.network_retry_timeout = int(value)
        
        return delta
                
    def _read(self):
        # Restore the default values
        self._update(self.defaults)

        try:
            f = open(self.persist_path)
            delta = f.read()
            f.close()
        
            # Read any values that have been persisted and apply them on top of the defaults
            ujson.loads(delta)
        except OSError:
            # If there are no persisted settings just move on
            pass

        
####################
# Logging Functions

EVENT_RUN=const(1)
EVENT_PURGE=const(2)
    
class RingLog:
    def __init__(self, LogEntry, size_limit):
        self.data = []
        self.size_limit = size_limit
        self.end_index = -1
        self.LogEntry = LogEntry
        self.console_log = False
    
    def log(self, log_tuple):
        end_index = self.end_index
        size_limit = self.size_limit

        if len(self.data) < size_limit:
            self.data.append(log_tuple)
            end_index += 1
        else:
            end_index = (end_index + 1) % size_limit
            self.data[end_index] = log_tuple
            
        self.end_index = end_index

        if self.console_log:
            print("Logged: " + str(log_tuple))
        
    # Outputs all entries in the log as tuple pairs without having to allocate one big string
    def dump(self, writer, since):
        first = True
        for log in self:
            if log.time > since:
                if not first:
                    writer.write(",")
                    first = False
                # TODO Not sure if this will work or makes sense. Perhaps should write out each field explicitly
                writer.write(json.dump(log))
        
    def __getitem__(self, index):
        return self.data[(index + self.end_index) % self.size_limit]
        
    def __len__(self):
        return len(self.data)

class EventLog(RingLog):
    def __init__(self):
        RingLog.__init__(self, namedtuple("Log", ("event", "start", "stop")), 400)
        self.console_log = True
    
    # Open a new log entry for the start time
    def log_start(self, event):
        start = time.time()
        self.log(self.LogEntry(event, start, start + 100000000))
        
    # Update the current log entry with the current time
    def log_stop(self):
        end_index = self.end_index
        event = self.data[end_index].event
        start = self.data[end_index].start
        stop = time.time()
        self.data[end_index] = self.LogEntry(event, start, stop)

    def calculate_duty(self, duration):
        now = time.time()
        # Clamp the start of the sample window to 0
        if now > duration:
            query_start = now - duration
        else:
            query_start = now
        
        # Find the total time that the compressor was running in the window (query_start - now)
        # NOTE: There is no need to iterate the logs in order. Iterating over self
        #       will do just that, but is slightly less efficient than iterating
        #       over self.data directly, so the iteration is over self.data.
        total_runtime = 0
        for log in self.data:
            # Logs that are 'open' will have a stop time in the distant future. Logs that
            # end within the interval may have started before it began. Clamp the stop and
            # stop times to the query window.
            start = max(query_start, log.start)
            stop = min(now, log.stop)
            # Count the time for this event if this is a run event in the window from
            # (query_start - now). Since the start and stop times of the log have been
            # clamped to the query window this can be tested by checking to see if the
            # clamped interval is not empty.
            if log.event == EVENT_RUN and stop > start:
                total_runtime += stop - start
        
        print("Compressor has run for %d of the last %d seconds." % (total_runtime, duration))
        # Return the percentage of the sample window where the compressor was running
        return total_runtime/duration

class StateLog(RingLog):
    def __init__(self, settings):
        RingLog.__init__(self, namedtuple("State", ("time", "pressure", "duty", "state")), 400)
        self.last_log_time = 0
        self.settings = settings
    
    def log_state(self, pressure, duty, state):
        now = int(time.time())
        since_last = now - self.last_log_time
        #print("now = " + str(now) + " since last " + str(since_last) + " Interval " + str(self.settings.log_interval))
        # TODO This True is only for debugging to fix a logging issue in simulator
        if True or since_last > self.settings.log_interval:
            self.last_log_time = now
            self.log(self.LogEntry(now, pressure, duty, state))

######################
# Compressor Functions
#

MOTOR_RUNNING = "running"
MOTOR_OFF = "off"
PURGE_PENDING = "about to purge"
PURGE_OPEN = "purging"

class Compressor:
    def __init__(self, activity_log, settings):
        self.activity_log = activity_log
        self.state_log = StateLog(settings)
        
        self.settings = settings
        
        # Configuration
        self.poll_interval = 1           # The time interval at which to update the compressor state
        
        # Setup state
        self.active = False              # The compressor will only run when this is True
        self.request_run_flag = False    # If this is True the compressor will run the next time that it can
        self.state = MOTOR_OFF           # True while the compressor is running, false when it is not
        self.shutdown_time = 0           # The time when the compressor is scheduled to shutdown

        # Locate hardware registers
        self.tank_pressure_ADC = machine.ADC(tank_pressure_pin)
        self.line_pressure_ADC = machine.ADC(line_pressure_pin)        
        self.compressor_motor = Pin(compressor_motor_pin, Pin.OUT)
        self.drain_solenoid = Pin(drain_solenoid_pin, Pin.OUT)
        
        # Ensure motor is stopped, solenoids closed
        self.compressor_motor.value(0)
        self.drain_solenoid.value(0)
        
    @property
    def tank_pressure(self):
        return self.settings.tank_pressure.map(self.tank_pressure_ADC.read_u16())
        
    @property
    def line_pressure(self):
        return self.settings.line_pressure.map(self.line_pressure_ADC.read_u16())
                
    @property
    def state_dictionary(self):
        # TODO 'Active' is not correct, it should be mapped to a state        
        return {
            "system_time": time.time(),
            "tank_pressure": self.tank_pressure,
            "line_pressure": self.line_pressure,
            "active": self.active,
            "state": self.state,
            "shutdown": self.shutdown_time,
            "duty_10": self.activity_log.calculate_duty(10),
            "duty_60": self.activity_log.calculate_duty(60)
        }        
    
    # The next time the compressor is updated it will start to run if it can
    def request_run(self):
        self.request_run_flag = True
    
    # Enables the on state. The motor will be automatically turned on and off
    # as needed based on the settings
    def compressor_on(self, shutdown_in):
        if shutdown_in == None:
            shutdown_in = self.settings.auto_stop_time
            
        if not self.active:
            self.active = True

            # If the shutdown parameter is > 0, schedule the shutdown relative to now
            if shutdown_in > 0:
                self.shutdown_time = time.time() + shutdown_in
    
    def compressor_off(self):
        # Make sure that the compressor is off
        self.pause()

        # If it was active before the call then
        # trigger any stop actions
        if self.active:
            # Clear the active flag and the shutdown time
            self.active = False
            self.shutdown_time = 0

            self.purge()
            self.activity_log.log_stop()

    def purge(self, duration = None, delay = None):
        self.purge_task = asyncio.create_task(self._purge(duration, delay))

    async def _purge(self, duration, delay):
        if duration is None:
            duration = self.settings.drain_duration
        if delay is None:
            delay = self.settings.drain_delay
            
        if duration > 0:
            self.state = PURGE_PENDING
            await asyncio.sleep(delay)
            # If the motor is running, stop it
            self.pause()
            
            # Open the drain solenoid
            self.drain_solenoid.value(1)            
            self.activity_log.log_start(EVENT_PURGE)
            self.state = PURGE_OPEN
            
            await asyncio.sleep(duration)
            self.drain_solenoid.value(0)    
            self.activity_log.log_stop()
            self.state = MOTOR_OFF

    def _run_motor(self):
        self.compressor_motor.value(1)
        self.drain_solenoid.value(0)
        
        if self.state != MOTOR_RUNNING:
            self.state = MOTOR_RUNNING
            self.activity_log.log_start(EVENT_RUN)

    def pause(self):
        self.compressor_motor.value(0)
        if self.state == MOTOR_RUNNING:
            self.state = MOTOR_OFF

    def _update(self):
        # Read the current tank pressure
        current_pressure = self.tank_pressure
        # If duty control is enabled calculate the current duty percentage
        max_duty = self.settings.max_duty
        if max_duty < 1:
            current_duty = self.activity_log.calculate_duty(self.settings.duty_duration)
        else:
            current_duty = 0

        self.state_log.log_state(current_pressure, current_duty, self.state)
                    
        # If the auto shutdown time has arrived schedule a shtudown task
        if self.shutdown_time > 0 and time.time() > self.shutdown_time and self.active:
            self.compressor_off()

        if not self.active or self.state == PURGE_OPEN or self.state == PURGE_PENDING:
            self.pause()
            return

        # If the sensor value is out of range then shut off the motor
        if current_pressure == None:
            self.sensor_error = True
        else:
            self.sensor_error = False
            
        if self.sensor_error:
            self.pause()
            return
            
        if max_duty < 1 and current_duty > max_duty:
            self.pause()
            # TODO If we have a 'next' compressor we could pass them a duty token
            #      so that they run, and disable self so that we do not. This isn't the
            #      best approach to load balancing though, so more thought is be required
            return

        if current_pressure > self.settings.stop_pressure:
            self.pause()
        elif current_pressure < self.settings.start_pressure or self.request_run:
            self.request_run_flag = False
            self._run_motor()

    async def _run(self):
        # Setup a watchdog timer to ensure that the compressor is always updated. If another coroutine
        # steals too many cycles the board will be rebooted rather than risking leaving the compressor
        # unattended.
        watchdog = WDT(timeout=2000)

        while True:
            watchdog.feed()
            self._update()
            await asyncio.sleep(self.poll_interval)
            
    def run(self):
        self.run_task = asyncio.create_task(self._run())
            
        
####################
# Network Functions
#

class Server:
    def __init__(self, compressor, settings):
        self.compressor = compressor
        self.settings = settings
        
    def _dump_json_header(self, writer):
        writer.write('HTTP/1.0 200 OK\r\nContent-type: text/json\r\n\r\n')
    
    def _return_json(self, writer, obj):
        self._dump_json_header(writer)
        json.dump(obj, writer)

    def _return_html_template(self, writer, template):
        # TODO This is pretty inefficient, since most keys wont have substitutions. It would
        #      be better to parse for tokens and only sub those.
        values = self.compressor.state_dictionary | self.settings.dictionary_representation

        for key, value in values.items():
            template = template.replace('$' + key + '$', value)
        
        writer.write('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
        writer.write(template)            
        
    async def _connect_to_network(self, max_retries):
        self.wlan = wlan = network.WLAN(network.STA_IF)
        
        wlan.active(True)
        wlan.config(pm = 0xa11140) # Disable power-save m
        wlan.connect(self.settings.ssid, self.settings.wlan_password)

        retries = max_retries
        while retries > 0 or max_retries == 0:
            if wlan.status() < 0 or wlan.status() >= 3:
                break
            retries -= 1
            print('waiting for connection...')
            await asyncio.sleep(1)

        if wlan.status() != 3:
            raise RuntimeError('network connection failed')
        else:
            print('connected')
            status = wlan.ifconfig()
            print('ip = ' + status[0])      

    async def _serve_client(self, reader, writer):
        print("Client connected")
        request_line = await reader.readline()

        # We are not interested in HTTP request headers, skip them
        while await reader.readline() != b"\r\n":
            pass
        
        (request_type, request, protocol) = split(' ', str(request_line))
        (endpoint, parameter_strings) = split('?', request)
        
        parameters = {}
        if not parameter_strings == None:
            kv = split('&', parameter_strings)
            for pair in kv:
                (key, value) = split('=', pair)
                
                parameters[key] = value

        print("Request: ", request_line)
        print("Request Type: ", request_type)
        print("Endpoint: ", endpoint)
        print("Parameters: ", parameter_strings, " found: ", len(parameters))

        compressor = self.compressor
            
        if request_type == 'GET':
            if endpoint == '/status':
                self._return_json(writer, compressor.state_dictionary)
            elif endpoint == '/activity_logs':
                # Return all state logs since a value supplied by the caller (or all logs if there is no since)
                self._dump_json_header(writer)
                writer.write('{"activity":[')
                compressor.activity_log.dump(writer, parameters.get('since', 0))
                writer.write(']}')
            elif endpoint == '/state_logs':
                # Return all state logs since a value supplied by the caller (or all logs if there is no since)
                self._dump_json_header(writer)
                writer.write('{"activity":[')
                compressor.state_log.dump(writer, parameters.get('since', 0))
                writer.write(']}')
            elif endpoint == '/settings':
                self._return_json(writer, self.settings.dictionary_representation)
            else:
                self._return_html_template(writer, html_status)
        elif request_type == 'UPDATE':
            if endpoint == '/run':
                compressor.request_run()
            elif endpoint == '/on':
                compressor.compressor_on(parameters.get("shutdown_in", None))
            elif endpoint == '/off':
                compressor.compressor_off()
            elif endpoint == '/pause':
                compressor.pause()
            elif endpoint == '/purge':
                compressor.purge(parameters.get("drain_duration", None), parameters.get("drain_delay", None))
            elif endpoint == '/settings':
                self.settings.update(parameters)
                pass
                    
        await writer.drain()
        await writer.wait_closed()
        print("Client disconnected")

    async def _run(self):
        while True:
            try:
                print('Connecting to Network...')
                await self._connect_to_network(0)
            
                print('Setting up webserver...')
                await asyncio.start_server(self._serve_client, "0.0.0.0", 80)
            except Exception as e:
                print(e)

            # Sleep for a while, then try to connect again
            await asyncio.sleep(self.settings.network_retry_timeout)

    def run(self):
        self.run_task = asyncio.create_task(self._run())

#######################
# Main

async def main():
    settings = Settings(default_settings)
    activity_log = EventLog()
    
    # Run the compressor no matter what. It is essential that the compressor pressure is monitored
    compressor = Compressor(activity_log, settings)
    compressor.run()
    
    if settings.compressor_on_power_up:
        compressor.compressor_on(None)
    
    # Catch any connection error, since it is non fatal. A connection is desired, but not required
    try:
        server = Server(compressor, settings)
        server.run()
    except:
        print("Network error. Running without API.")
    
    # Loop forever while the coroutines process
    while True:
        await asyncio.sleep(1)

# TODO Not sure about the implications of this finally block
try:
    asyncio.run(main())
finally:
    asyncio.new_event_loop()

