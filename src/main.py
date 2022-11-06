import network
import socket
from settings import Settings
from settings import ValueScale
from server import Server
from server import flatten_dict
from ringlog import RingLog
from emptylock import EmptyLock

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
    def setup_properties(self, defaults):
        self.private_keys = ('wlan_password')
        self.values['tank_pressure_sensor'] = ValueScale(defaults['tank_pressure_sensor'])
        self.values['line_pressure_sensor'] = ValueScale(defaults['line_pressure_sensor'])

# Static settings
tank_pressure_pin = const(0)
line_pressure_pin = const(1)
compressor_motor_pin = const(15)
drain_solenoid_pin = const(14)
compressor_motor_status_pin = const("LED")
compressor_active_status_pin = const(2)
purge_active_status_pin = const(3)
use_multiple_threads = False
        
####################
# Logging Functions

EVENT_RUN=const(b'R')
EVENT_PURGE=const(b'P')

class EventLog(RingLog):
    def __init__(self):
        RingLog.__init__(self, "LLs", ["start", "stop", "event"], 40)
        self.console_log = False
        self.activity_open = False
    
    def d(self):
        print("== history")
        for i in range(len(self)):
            print(self[i])
        print("==")
        
    # Open a new log entry for the start time
    def log_start(self, event):
        start = time.time()
        # TODO Instead of + 1000000 this should just be int max, for the max possible time
        self.log((start, start + 100000000, event))
        self.activity_open = True
        
    # Update the current log entry with the current time
    def log_stop(self):
        if self.activity_open:
            # Grab the most recent log (for the open activity)
            current_log = self[0]
            
            # Extract the log properties
            event = current_log[2]
            start = current_log[0]
            
            stop = time.time()
            
            # Update the log with the current time as the stop time
            self[0] = (start, stop, event)
            self.activity_open = False
            
    def calculate_duty(self, duration):
        now = time.time()
        # Clamp the start of the sample window to 0
        if now > duration:
            query_start = now - duration
        else:
            query_start = now
        
        # Find the total time that the compressor was running in the window (query_start - now)
        total_runtime = 0
        for i in range(len(self)):
            log = self[i]
            event = log[2]
            # Logs that are 'open' will have a stop time in the distant future. Logs that
            # end within the interval may have started before it began. Clamp the stop and
            # stop times to the query window.
            start = max(query_start, log[0])
            stop = min(now, log[1])
            #print("calculate_duty have log: start = %d stop = %d" % (start, stop))
            # Count the time for this event if this is a run event in the window from
            # (query_start - now). Since the start and stop times of the log have been
            # clamped to the query window this can be tested by checking to see if the
            # clamped interval is not empty.
            if event == EVENT_RUN and stop > start:
                total_runtime += stop - start
        
        duty = total_runtime/duration
    
        # For debugging the duty calculations can be logged
        #print("Compressor has run for %d of the last %d seconds. Duty cycle is %f%%" % (total_runtime, duration, duty*100))
        
        # Return the percentage of the sample window where the compressor was running
        return duty
    
COMMAND_ON=const(b'O')
COMMAND_OFF=const(b'F')
COMMAND_RUN=const(b'R')
COMMAND_PAUSE=const(b'|')
COMMAND_PURGE=const(b'P')

class CommandLog(RingLog):
    def __init__(self):
        RingLog.__init__(self, "Ls", ["time", "command"], 10)
        self.console_log = False

    def log_command(self, event):
        self.log((time.time(), event))

class StateLog(RingLog):
    def __init__(self, settings):
        RingLog.__init__(self, "Lfff3s", ["time", "tank_pressure", "line_pressure", "duty", "state"], 200)
        self.last_log_time = 0
        self.settings = settings
        self.console_log = False
    
    def log_state(self, tank_pressure, line_pressure, duty, state):
        now = int(time.time())
        since_last = now - self.last_log_time
        #print("now = " + str(now) + " since last " + str(since_last) + " Interval " + str(self.settings.log_interval))
        if since_last > self.settings.log_interval:
            self.last_log_time = now
            self.log((now, -1 if tank_pressure is None else tank_pressure,
                           -1 if line_pressure is None else line_pressure, duty, state))
            
    @property
    def max_duration(self):
        return self.settings.log_interval * self.size_limit
            
######################
# Compressor Functions
#

MOTOR_STATE_RUN=const('run')                    # lower pressure limit reached, motor on
MOTOR_STATE_OFF=const('off')                    # compressor is in off mode
MOTOR_STATE_SENSOR_ERROR=const('sensor_error')  # error reading pressure sensor
MOTOR_STATE_PAUSE=const('pause')                # user pause requested
MOTOR_STATE_PRESSURE=const('overpressure')      # upper pressure limit reached
MOTOR_STATE_DUTY=const('duty')                  # duty limit reached
MOTOR_STATE_PURGE=const('purge')                # purging in progress, motor disabled

# Compressor monitors the state of the compressor and controls the
# motor and drain valve.
#
# Compressor is designed so that it can be run as a coroutine, or on
# hardware that supports it, as a background thread. Running as a thread
# means that there's no risk of a foreground coroutine stealing all of the
# cycles and leaving the compressor update task unmonitored.
#
# All of the public access methods acquire a lock so that the state of the
# compressor isn't being queried while its updated. It is thus safe to call
# any of the public methods from another thread.
#
# The logs used by the compressor are only updated while a lock is held, so
# if a caller wants to access the logs it should aquire compressor.lock first
# to ensure that the logs aren't mutated while they are being read.
class Compressor:
    def __init__(self, settings, thread_safe = False):
        self.activity_log = EventLog()
        self.command_log = CommandLog()
        self.state_log = StateLog(settings)
        
        self.settings = settings
        self.lock = EmptyLock.create_lock(thread_safe)
        self.thread_safe = thread_safe
        
        # Configuration
        self.poll_interval = 1           # The time interval at which to update the compressor state
        
        # Setup state
        self.compressor_is_on = False    # The compressor will only run when this is True
        self.request_run_flag = False    # If this is True the compressor will run the next time that it can
        self.motor_state = MOTOR_STATE_OFF  # MOTOR_STATE_RUN if the motor is running, otherwise the reason it is not
        self.purge_valve_open = False    # True when the purge valve is open, false when it is not
        self.purge_pending = False       # True when a purge is pending, false when it is not
        self.shutdown_time = 0           # The time when the compressor is scheduled to shutdown
        self.duty_recovery_time = 0      # The time when the motor will have recovered from the last duty cycle violation

        # Locate hardware registers
        self.tank_pressure_ADC = machine.ADC(tank_pressure_pin)
        self.line_pressure_ADC = machine.ADC(line_pressure_pin)        
        self.compressor_motor = Pin(compressor_motor_pin, Pin.OUT)
        self.drain_solenoid = Pin(drain_solenoid_pin, Pin.OUT)
        self.motor_status = machine.Pin(compressor_motor_status_pin, machine.Pin.OUT)
        self.compressor_on_status = machine.Pin(compressor_active_status_pin, machine.Pin.OUT)
        self.purge_status = machine.Pin(purge_active_status_pin, machine.Pin.OUT)

        # Ensure motor is stopped, solenoids closed
        self.compressor_motor.value(0)
        self.drain_solenoid.value(0)
        
        # Set the initial status values
        self._update_status()

    def _update_status(self):
        # TODO For reasons that I cannot fathom, updating the LED from a thread
        #      is causing the thread to deadlock. I can disable this for now.
        #      I was intending to move this code to the UI update thread anyhow
        if not self.thread_safe:
            self.motor_status.value(self.compressor_motor.value())
        self.compressor_on_status.value(self.compressor_is_on)
        self.purge_status.value(self.drain_solenoid.value())
    
    def _read_ADC(self):
        self.tank_pressure = self.settings.tank_pressure_sensor.map(self.tank_pressure_ADC.read_u16())        
        self.line_pressure = self.settings.line_pressure_sensor.map(self.line_pressure_ADC.read_u16())
    
    @property
    def _state(self):
        if self.motor_state == MOTOR_STATE_RUN:
            short_state = 'R'
        elif self.motor_state == MOTOR_STATE_OFF:
            short_state = 'f'
        elif self.motor_state == MOTOR_STATE_SENSOR_ERROR:
            short_state = 's'
        elif self.motor_state == MOTOR_STATE_PAUSE:
            short_state = '|'
        elif self.motor_state == MOTOR_STATE_PRESSURE:
            short_state = 'p'
        elif self.motor_state == MOTOR_STATE_DUTY:
            short_state = 'd'
        elif self.motor_state == MOTOR_STATE_PURGE:
            short_state = '*'
        else:
            '_'

        return ('O' if self.compressor_is_on else '_') + short_state + ('P' if self.purge_valve_open else '_')
    
    @property
    def state_dictionary(self):        
        with self.lock:
            self._read_ADC()
            
            tank_pressure = -1 if self.tank_pressure is None else self.tank_pressure
            line_pressure = -1 if self.line_pressure is None else self.line_pressure
            
            with self.settings.lock:
                start_pressure = self.settings.start_pressure
                min_line_pressure = self.settings.min_line_pressure
                duty_duration = self.settings.duty_duration
            
            return {
                "system_time": time.time(),
                "tank_pressure": tank_pressure,
                "line_pressure": line_pressure,
                "tank_underpressure": tank_pressure < start_pressure,
                "line_underpressure": line_pressure < min_line_pressure or
                                      tank_pressure < min_line_pressure,
                "compressor_on": self.compressor_is_on,
                "motor_state": self.motor_state,
                "run_request": self.request_run_flag,
                "purge_open": self.purge_valve_open,
                "purge_pending": self.purge_pending,
                "shutdown": self.shutdown_time,
                "duty_recovery_time": self.duty_recovery_time,
                "duty": self.activity_log.calculate_duty(duty_duration),
                "duty_60": self.activity_log.calculate_duty(60*60)
            }        
    
    # The next time the compressor is updated it will start to run if it can
    def request_run(self):
        with self.lock:
            self.request_run_flag = True
            self.command_log.log_command(COMMAND_RUN)
    
    # Enables the on state. The motor will be automatically turned on and off
    # as needed based on the settings
    def compressor_on(self, shutdown_in):
        with self.lock:        
            if shutdown_in == None:
                shutdown_in = self.settings.auto_stop_time
                
            if not self.compressor_is_on:
                self.command_log.log_command(COMMAND_ON)
                self.compressor_is_on = True

                # If the shutdown parameter is > 0, schedule the shutdown relative to now
                if shutdown_in > 0:
                    self.shutdown_time = time.time() + shutdown_in
    
    def compressor_off(self):
        with self.lock:
            # Make sure that the compressor is off
            self._pause(MOTOR_STATE_OFF)

            # If it was active before the call then
            # trigger any stop actions
            if self.compressor_is_on:
                self.command_log.log_command(COMMAND_OFF)            
                # Clear the active flag and the shutdown time
                self.compressor_is_on = False
                self.shutdown_time = 0

                self.purge()

    def purge(self, duration = None, delay = None):
        with self.lock:
            self.command_log.log_command(COMMAND_PURGE)
        self.purge_task = asyncio.create_task(self._purge(duration, delay))

    # NOTE: Unlike most private Compressor methods, this runs as a coroutine
    #       On the foreground thread, not on the background thread. Thus it
    #       must aquire a lock before performing any compressor specific actions
    async def _purge(self, duration, delay):
        if duration is None:
            duration = self.settings.drain_duration
        if delay is None:
            delay = self.settings.drain_delay
            
        if duration > 0:
            with self.lock:
                self.purge_pending = True
            await asyncio.sleep(delay)
            with self.lock:
                # If the motor is running, stop it
                self._pause(MOTOR_STATE_PURGE)
                
                # Open the drain solenoid
                self.drain_solenoid.value(1)            
                self.activity_log.log_start(EVENT_PURGE)
                self.purge_pending = False
                self.purge_valve_open = True
            
            await asyncio.sleep(duration)
            with self.lock:
                self.drain_solenoid.value(0)    
                self.activity_log.log_stop()
                self.purge_valve_open = False

    def _run_motor(self):
        self.compressor_motor.value(1)
        self.drain_solenoid.value(0)
        
        if self.motor_state != MOTOR_STATE_RUN:
            self.motor_state = MOTOR_STATE_RUN
            self.activity_log.log_start(EVENT_RUN)

    def pause(self):
        with self.lock:
            self.command_log.log_command(COMMAND_PAUSE)
            self._pause(MOTOR_STATE_PAUSE)
        
    def _pause(self, reason):
        self.compressor_motor.value(0)
        self.activity_log.log_stop()
        self.motor_state = reason


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

        self.state_log.log_state(current_pressure, self.line_pressure, current_duty, self._state)
                    
        # If the auto shutdown time has arrived schedule a shtudown task
        if self.shutdown_time > 0 and current_time > self.shutdown_time and self.compressor_is_on:
            self.compressor_off()

        if not self.compressor_is_on:
            self._pause(MOTOR_STATE_OFF)
            return
        if self.purge_valve_open or self.purge_pending:
            self._pause(MOTOR_STATE_PURGE)
            return

        # If the sensor value is out of range then shut off the motor
        if current_pressure == None:
            self._pause(MOTOR_STATE_SENSOR_ERROR)
            return
                        
        if current_time < self.duty_recovery_time:
            self._pause(MOTOR_STATE_DUTY)
            return
        
        if max_duty < 1 and current_duty > max_duty:
            # If the motor is currently running trigger a request to run again once
            # the duty cycle condition is cleared
            self.request_run_flag = self.request_run_flag or self.motor_state == MOTOR_STATE_RUN

            self._pause(MOTOR_STATE_DUTY)
            # TODO recovery_time could be calculated by averaging (or taking the  max) of the last few
            #      run cycles. For now it's just a setting
            self.duty_recovery_time = current_time + self.settings.recovery_time
            # TODO If we have a 'next' compressor we could pass them a duty token
            #      so that they run, and disable self so that we do not. This isn't the
            #      best approach to load balancing though, so more thought is be required
            return

        if current_pressure > self.settings.stop_pressure:
            self._pause(MOTOR_STATE_PRESSURE)
        elif current_pressure < self.settings.start_pressure or self.request_run_flag:
            self.request_run_flag = False
            self._run_motor()

    async def _run(self):
        print("WARNING: No watchdog timer in single thread mode. This is potentially dangerous.")
        while True:                
            self._update()
            self._update_status()
            await asyncio.sleep(self.poll_interval)
        
    def _run_thread(self):
        # Setup a watchdog timer to ensure that the compressor is always updated. If something
        # steals too many cycles the board will be rebooted rather than risk leaving the compressor
        # unattended.
        watchdog = WDT(timeout=2000)
        
        while True:
            watchdog.feed()
            
            with self.lock:
                self._update()
                self._update_status()
            # Put the thread to sleep
            time.sleep(self.poll_interval)
        
        print("WARNING: Background thread event loop has finished")
         
    def run(self):
        if self.thread_safe:
            print("Compressor instance is threadsafe. Starting a background thread.")
            _thread.start_new_thread(self._run_thread, ())        
        else:            
            # Note that no watchdog is created in this case. Unfortunately some of the networking
            # calls aren't 100% async and may block long enough to allow the interrupt to fire
            # This makes running in single threaded mode somewhat suspect
            print("Compressor instance is not threadsafe. Running using coroutines.")
            self.run_task = asyncio.create_task(self._run())

####################
# Network Functions
#

class CompressorServer(Server):
    def __init__(self, compressor, settings):
        Server.__init__(self, settings, True)
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
                    # The compressor needs to be locked so that the logs can be accessed. To prevent
                    # holding the lock for too long, the dump commands set blocking to False. But this
                    # will require the buffer to hold all of the data that is being sent, so it is a memory
                    # consumption risk.
                    with compressor.lock:
                        # Return all activity logs that end after since
                        await compressor.activity_log.dump(writer, int(parameters.get('since', 0)), 1, blocking = not compressor.thread_safe)
                        writer.write('],"commands":[')
                        # Return all command logs that fired after since
                        await compressor.command_log.dump(writer, int(parameters.get('since', 0)), blocking = not compressor.thread_safe)
                    writer.write(']}')
                elif endpoint == '/state_logs':
                    # Return all state logs since a value supplied by the caller (or all logs if there is no since)
                    self.response_header(writer)
                    # The compressor needs to be locked so that the logs can be accessed. To prevent
                    # holding the lock for too long, the dump commands set blocking to False. But this
                    # will require the buffer to hold all of the data that is being sent, so it is a memory
                    # consumption risk.
                    with compressor.lock:
                        writer.write('{"time":' + str(time.time()) + ',"maxDuration":' + str(compressor.state_log.max_duration) + ',"state":[')
                        await compressor.state_log.dump(writer, int(parameters.get('since', 0)), blocking = compressor.thread_safe)
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
                
    def handle_request(self, cl):
        rawBytes = b''
        while rawBytes.find(b'\r\n') < 0:
            rawBytes = rawBytes + cl.recv(128)

        lines = rawBytes.split(b'\r\n')
        if len(lines) > 0:
            self._parse_request(lines[0])
        
        cl.send('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
        cl.send('<html><head></head><body><h1>Response</h1></body></html>')

#######################
# Main

async def startUI(compressor, settings):
    # Catch any connection error, since it is non fatal. A connection is desired, but not required
    try:
        global server
        server = CompressorServer(compressor, settings)
        server.run()
        # TODO Since run only schedules a coroutine, I doubt that this exception is ever hit
    except Exception as e:
        print("Network error. Running without API.")
        sys.print_exception(e)
    
    # Loop forever while the coroutines process
    #asyncio.get_event_loop().run_forever()
    while True:
        await asyncio.sleep(10000)

    print("WARNING: UI co-routines are done.")
    
async def main():
    settings = CompressorSettings(default_settings, thread_safe = use_multiple_threads)
    
    # Run the compressor no matter what. It is essential that the compressor
    # pressure is monitored
    compressor = Compressor(settings, thread_safe = use_multiple_threads)
    compressor.run()
    
    if settings.compressor_on_power_up:
        compressor.compressor_on(None)
    
    await startUI(compressor, settings)


# TODO Not sure about the implications of this finally block
try:
    asyncio.run(main())
finally:
    asyncio.new_event_loop()


