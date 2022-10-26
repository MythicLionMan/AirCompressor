import network
import socket
from settings import Settings
from server import Server

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
    "recovery_time": 3*60,
    "drain_delay": 5,
    "compressor_on_power_up": True,
    "auto_stop_time": 6*60*60,
    "log_interval": 10,
    
    # WiFi configuration
    "ssid": 'A Network',
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
compressor_motor_status_pin = const("LED")
compressor_active_status_pin = const(2)
purge_active_status_pin = const(3)

# HTML Templates

html_status = """<!DOCTYPE html>
<html>
    <head><title>Air Compressor</title></head>
    <body>
        <h1>Air Compressor</h1>

        <h2>State</h2>
        <table>
            <tr><td>System Time</td><td>{system_time}</td></tr>
            <tr><td>Tank Pressure</td><td>{tank_pressure}</td></tr>
            <tr><td>Line Pressure</td><td>{line_pressure}</td></tr>
            <tr><td>Active</td><td>{active}</td></tr>
            <tr><td>State</td><td>{state}</td></tr>
            <tr><td>Shutdown</td><td>{shutdown}</td></tr>
            <tr><td>Duty Recovery Time</td><td>{duty_recovery_time}</td></tr>
            <tr><td>Duty 10 Minutes</td><td>{duty_10}</td></tr>
            <tr><td>Duty 60 Minutes</td><td>{duty_60}</td></tr>
        </table>
        <h2>Settings</h2>
        <table>
            <tr><td>Start Pressure</td><td>{start_pressure}</td></tr>
            <tr><td>Stop Pressure</td><td>{stop_pressure}</td></tr>
            <tr><td>Max Duty</td><td>{max_duty}</td></tr>
            <tr><td>Duty Duration</td><td>{duty_duration}</td></tr>
            <tr><td>Recovery Time</td><td>{recovery_time}</td></tr>
            <tr><td>Drain Duration</td><td>{drain_duration}</td></tr>
            <tr><td>Drain Delay</td><td>{drain_delay}</td></tr>
            <tr><td>Compressor On Power Up</td><td>{compressor_on_power_up}</td></tr>
            <tr><td>Auto Stop Time</td><td>{auto_stop_time}</td></tr>
            <tr><td>Log Interval</td><td>{log_interval}</td></tr>
        </table>
    </body>
</html>
"""
        
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
            print("Logged[{}]: {}".format(end_index, log_tuple))
        
    # Outputs all entries in the log as tuple pairs without having to allocate one big string
    def dump(self, writer, since):
        first = True
        # TODO Iterating over self.data instead of self means that the entries are not in order
        #      There's a bug though, where iterating over self only returns a single log.
        for log in self.data:
            if log.time > since:
                if not first:
                    writer.write(",")
                first = False
                # TODO Not if this makes sense. Perhaps should write out each field explicitly
                #      It isn't quite correct json.
                writer.write(ujson.dumps(log))
        
    def __getitem__(self, index):
        return self.data[(index + self.end_index) % self.size_limit]
        
    def __len__(self):
        return len(self.data)

class EventLog(RingLog):
    def __init__(self):
        RingLog.__init__(self, namedtuple("Log", ("event", "time", "stop")), 400)
        self.console_log = True
        self.activity_open = False
    
    # Open a new log entry for the start time
    def log_start(self, event):
        start = time.time()
        self.log(self.LogEntry(event, start, start + 100000000))
        self.activity_open = True
        
    # Update the current log entry with the current time
    def log_stop(self):
        end_index = self.end_index
        if end_index >= 0 and self.activity_open:
            event = self.data[end_index].event
            start = self.data[end_index].time
            stop = time.time()
            #print("log_stop() start = %d stop = %d index = %d" % (start, stop, end_index))
            self.data[end_index] = self.LogEntry(event, start, stop)
            self.activity_open = False

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
            start = max(query_start, log.time)
            stop = min(now, log.stop)
            #print("calculate_duty have log: start = %d stop = %d" % (start, stop))
            # Count the time for this event if this is a run event in the window from
            # (query_start - now). Since the start and stop times of the log have been
            # clamped to the query window this can be tested by checking to see if the
            # clamped interval is not empty.
            if log.event == EVENT_RUN and stop > start:
                total_runtime += stop - start
        
        duty = total_runtime/duration
    
        # For debugging the duty calculations can be logged
        #print("Compressor has run for %d of the last %d seconds. Duty cycle is %f%%" % (total_runtime, duration, duty*100))
        
        # Return the percentage of the sample window where the compressor was running
        return duty

class StateLog(RingLog):
    def __init__(self, settings):
        RingLog.__init__(self, namedtuple("State", ("time", "pressure", "duty", "state")), 400)
        self.last_log_time = 0
        self.settings = settings
        self.console_log = True
    
    def log_state(self, pressure, duty, state):
        now = int(time.time())
        since_last = now - self.last_log_time
        #print("now = " + str(now) + " since last " + str(since_last) + " Interval " + str(self.settings.log_interval))
        if since_last > self.settings.log_interval:
            self.last_log_time = now
            self.log(self.LogEntry(now, pressure, duty, state))

######################
# Compressor Functions
#

# TODO This should be a bit mask, since MOTOR_RUNNING is independent of PURGE_PENDING and PURGE_OPEN. And if
#      we get to that state, perhaps this should be auto synthesized from the actual pin values.
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
        self.duty_recovery_time = 0      # The time when the motor will have recovered from the last duty cycle violation

        # Locate hardware registers
        self.tank_pressure_ADC = machine.ADC(tank_pressure_pin)
        self.line_pressure_ADC = machine.ADC(line_pressure_pin)        
        self.compressor_motor = Pin(compressor_motor_pin, Pin.OUT)
        self.drain_solenoid = Pin(drain_solenoid_pin, Pin.OUT)
        self.motor_status = machine.Pin(compressor_motor_status_pin, machine.Pin.OUT)
        self.active_status = machine.Pin(compressor_active_status_pin, machine.Pin.OUT)
        self.purge_status = machine.Pin(purge_active_status_pin, machine.Pin.OUT)

        # Ensure motor is stopped, solenoids closed
        self.compressor_motor.value(0)
        self.drain_solenoid.value(0)
        
        # Set the initial status values
        self._update_status()

    def _update_status(self):
        self.motor_status.value(self.compressor_motor.value())
        self.active_status.value(self.active)
        self.purge_status.value(self.drain_solenoid.value())
    
    def _read_ADC(self):
        self.tank_pressure = self.settings.tank_pressure.map(self.tank_pressure_ADC.read_u16())        
        self.line_pressure = self.settings.line_pressure.map(self.line_pressure_ADC.read_u16())
                
    @property
    def state_dictionary(self):
        self._read_ADC()
        
        # TODO 'Active' is not correct, it should be mapped to a state        
        return {
            "system_time": time.time(),
            "tank_pressure": self.tank_pressure,
            "line_pressure": self.line_pressure,
            "active": self.active,
            "state": self.state,
            "shutdown": self.shutdown_time,
            "duty_recovery_time": self.duty_recovery_time,
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
        self.activity_log.log_stop()
        if self.state == MOTOR_RUNNING:
            self.state = MOTOR_OFF

    def _update(self):
        self._read_ADC()
        
        current_time = time.time()
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
        if self.shutdown_time > 0 and current_time > self.shutdown_time and self.active:
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
            
        if current_time < self.duty_recovery_time:
            self.pause()
            return
        
        if max_duty < 1 and current_duty > max_duty:
            self.pause()
            # TODO recovery_time could be calculated by averaging (or taking the  max) of the last few
            #      run cycles. For now it's just a setting
            # TODO What should happen when the duty_recovery_time arrives? Right now the compressor will
            #      remain off until the tank pressure drops again. But perhaps it should cycle back on
            #      automatically to bring the tank pressure back up since it was running when it was stopped.
            #      This could be easily handled by setting request_run to true if the motor is currently running.
            self.duty_recovery_time = current_time + self.settings.recovery_time
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
        # TODO Disabling the watchdog because some of the networking calls aren't 100% async
        #      This needs to be resolved before production
        #watchdog = WDT(timeout=2000)

        while True:
            #watchdog.feed()
            self._update()
            self._update_status()
            await asyncio.sleep(self.poll_interval)
            
    def run(self):
        self.run_task = asyncio.create_task(self._run())
            
####################
# Network Functions
#

class CompressorServer(Server):
    def __init__(self, compressor, settings):
        Server.__init__(self, settings, True)
        self.compressor = compressor
    
    def return_html_template(self, writer, template):
        values = {}
        values.update(self.compressor.state_dictionary)
        values.update(self.settings.dictionary_representation)
        
        self.response_header(writer, content_type = 'text/html')
        writer.write(template.format(**values))

    def return_ok(self, writer):
        self.return_json(writer, {'result':'ok'})
    
    def _parse_request(self, request_line):
        (request_type, request, protocol) = request_line.decode('ascii').split()

        tokens = request.split('?')

        if len(tokens) == 0:
            endpoint = ''
            parameter_strings = None
        elif len(tokens) == 1:
            endpoint = str(tokens[0])
            parameter_strings = None
        elif len(tokens) == 2:
            endpoint = str(tokens[0])
            parameter_strings = str(tokens[1])
        
        parameters = {}
        if not parameter_strings == None:
            kv = parameter_strings.split('&')
            for pair in kv:
                (key, value) = pair.split('=')
                
                parameters[key] = value

        print("Request: ", request_line)
        print("Request Type: '{}'".format(request_type))
        print("Endpoint: '{}'".format(endpoint))
        print("Parameters: '{}' found: {}".format(parameter_strings, len(parameters)))
        
        return (request_type, endpoint, parameters)

    async def serve_client(self, reader, writer):
        request_line = await reader.readline()

        # We are not interested in HTTP request headers, skip them
        while await reader.readline() != b"\r\n":
            pass
        
        (request_type, endpoint, parameters) = self._parse_request(request_line)

        compressor = self.compressor
            
        if request_type == 'GET':
            if endpoint == '/settings':
                if len(parameters) > 0:
                    try:
                        self.settings.update(parameters)
                        self.settings.write_delta()
                        
                        self.return_json(writer, self.settings.dictionary_representation)
                    except KeyError as e:
                        self.return_json(writer, {'result':'unknown key error', 'missing key': e}, 400)                    
                else:
                    self.return_json(writer, self.settings.dictionary_representation)
            if len(parameters) > 0:
                self.return_json(writer, {'result':'unexpected parameters'}, 400)
            elif endpoint == '/':
                self.return_html_template(writer, html_status)                
            elif endpoint == '/status':
                self.return_json(writer, compressor.state_dictionary)
            elif endpoint == '/activity_logs':
                # Return all state logs since a value supplied by the caller (or all logs if there is no since)
                self.response_header(writer)
                writer.write('{"activity":[')
                compressor.activity_log.dump(writer, parameters.get('since', 0))
                writer.write(']}')
            elif endpoint == '/state_logs':
                # Return all state logs since a value supplied by the caller (or all logs if there is no since)
                self.response_header(writer)
                writer.write('{"state":[')
                compressor.state_log.dump(writer, parameters.get('since', 0))
                writer.write(']}')
            elif endpoint == '/run':
                compressor.request_run()
                self.return_ok(writer)
            elif endpoint == '/on':
                compressor.compressor_on(parameters.get("shutdown_in", None))
                self.return_ok(writer)
            elif endpoint == '/off':
                compressor.compressor_off()
                self.return_ok(writer)
            elif endpoint == '/pause':
                compressor.pause()
                self.return_ok(writer)
            elif endpoint == '/purge':
                compressor.purge(parameters.get("drain_duration", None), parameters.get("drain_delay", None))
                self.return_ok(writer)
            else:
                self.return_json(writer, {'result':'unknown endpoint'}, 404)
        elif request_type == 'PUT':
            self.return_json(writer, {'result':'unknown endpoint'}, 404)
        else:
            self.return_json(writer, {'result':'unknown method'}, 404)
            
                    
        await writer.drain()
        await writer.wait_closed()
                
    def handle_request(self, cl):
        rawBytes = b''
        while rawBytes.find(b'\r\n') < 0:
            rawBytes = rawBytes + cl.recv(128)

        lines = rawBytes.split(b'\r\n')
        if len(lines) > 0:
            self._parse_request(lines[0])
        
        cl.send('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
        cl.send('<html><head></head><body><h1>Response</h1></body></html>')
        cl.close()


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
        global server
        server = CompressorServer(compressor, settings)
        server.run()
    except Exception as e:
        print("Network error. Running without API.")
        print(e)
    
    # Loop forever while the coroutines process
    #asyncio.get_event_loop().run_forever()
    while True:
        await asyncio.sleep(10000)
    print("Main() is done.")

# TODO Not sure about the implications of this finally block
try:
    asyncio.run(main())
finally:
    asyncio.new_event_loop()


