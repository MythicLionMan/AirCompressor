from settings import Settings
from settings import ValueScale
from ringlog import RingLog
from condlock import CondLock
from heartbeatmonitor import HeartbeatMonitor

import compressorlogs
from compressorlogs import EventLog
from compressorlogs import CommandLog
from compressorlogs import StateLog

import time
import sys
import _thread

import machine
from machine import Pin
from machine import WDT
import uasyncio as asyncio
    
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
class CompressorController:
    def __init__(self, settings, thread_safe = False):
        self.activity_log = EventLog(thread_safe = thread_safe)
        self.command_log = CommandLog(thread_safe = thread_safe)
        self.state_log = StateLog(settings, thread_safe = thread_safe)
        
        self.settings = settings
        self.lock = CondLock(thread_safe)
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
        self.tank_sensor_error = False   # The tank pressure sensor has detected an out of range value
        self.line_sensor_error = False   # The line pressure sensor has detected an out of range value
        self.running = False
        
        # Locate hardware registers
        self.tank_pressure_ADC = machine.ADC(settings.tank_pressure_pin)
        if settings.line_pressure_pin is not None:
            self.line_pressure_ADC = machine.ADC(settings.line_pressure_pin)
        else:
            self.line_pressure_ADC = None
        self.compressor_motor = Pin(settings.compressor_motor_pin, Pin.OUT)
        self.drain_solenoid = Pin(settings.drain_solenoid_pin, Pin.OUT)

        # Ensure motor is stopped, solenoids closed
        self.compressor_motor.value(0)
        self.drain_solenoid.value(0)
    
    def _read_ADC(self):
        self.tank_pressure = self.settings.tank_pressure_sensor.map(self.tank_pressure_ADC.read_u16())
        # If either sensor returns None there is an error. Record the error, and then
        # set the value to -1 so that it is a valid integer for calculations and serialization
        self.tank_sensor_error = self.tank_pressure is None
        if self.tank_pressure is None:
            self.tank_pressure = -1

        if self.line_pressure_ADC is not None:
            self.line_pressure = self.settings.line_pressure_sensor.map(self.line_pressure_ADC.read_u16())
            self.line_sensor_error = self.line_pressure is None
            if self.line_pressure is None:
                self.line_pressure = -1
        else:
            self.line_pressure = self.tank_pressure
            self.line_sensor_error = self.tank_sensor_error
            
    @property
    def _state_string(self):
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
            
            tank_pressure = self.tank_pressure
            line_pressure = self.line_pressure
            line_sensor_error = self.line_sensor_error
            
            with self.settings.lock:
                start_pressure = self.settings.start_pressure
                min_line_pressure = self.settings.min_line_pressure
                duty_duration = self.settings.duty_duration
            
            return {
                "system_time": time.time(),
                "tank_pressure": tank_pressure,
                "line_pressure": line_pressure,
                "tank_underpressure": tank_pressure < start_pressure,
                "line_underpressure": (tank_pressure < min_line_pressure) if line_sensor_error else\
                                      line_pressure < min_line_pressure,
                "tank_sensor_error": self.tank_sensor_error,
                "line_sensor_error": line_sensor_error,
                "compressor_on": self.compressor_is_on,
                "motor_state": self.motor_state,
                "run_request": self.request_run_flag,
                "purge_open": self.purge_valve_open,
                "purge_pending": self.purge_pending,
                "shutdown": self.shutdown_time,
                "duty_recovery_time": self.duty_recovery_time,
                "duty": self.activity_log.calculate_duty(duty_duration),
                # TODO Maybe this should be runtime in the last 60 minutes, since
                #      that's the question it would be answering
                "duty_60": self.activity_log.calculate_duty(60*60)
            }        
                
    # The next time the compressor is updated it will start to run if it can
    def request_run(self):
        with self.lock:
            self.request_run_flag = True
            self.command_log.log_command(compressorlogs.COMMAND_RUN)
    
    # Toggles the on state in a thread safe way
    def toggle_on_state(self):
        with self.lock:
            if self.compressor_is_on:
                self.compressor_off()
            else:
                self.compressor_on()
                
    # Toggles the run/pause state in a thread safe way
    def toggle_run_state(self):
        with self.lock:
            if self.request_run_flag:
                self.request_run_flag = False
            elif self.motor_state == MOTOR_STATE_RUN:
                self.pause()
            else:
                self.request_run()
                
    # Enables the on state. The motor will be automatically turned on and off
    # as needed based on the settings
    def compressor_on(self, shutdown_in = None):
        with self.lock:        
            if shutdown_in == None:
                shutdown_in = self.settings.auto_stop_time
                
            if not self.compressor_is_on:
                self.command_log.log_command(compressorlogs.COMMAND_ON)
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
                self.command_log.log_command(compressorlogs.COMMAND_OFF)            
                # Clear the active flag and the shutdown time
                self.compressor_is_on = False
                self.shutdown_time = 0

                self.purge()

    def purge(self, duration = None, delay = None):
        self.command_log.log_command(compressorlogs.COMMAND_PURGE)
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
                self.activity_log.log_start(compressorlogs.EVENT_PURGE)
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
            self.activity_log.log_start(compressorlogs.EVENT_RUN)

    def pause(self):
        with self.lock:
            self.command_log.log_command(compressorlogs.COMMAND_PAUSE)
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

        self.state_log.log_state(current_pressure, self.line_pressure, current_duty, self._state_string)
                    
        # If the auto shutdown time has arrived schedule a shtudown task
        if self.shutdown_time > 0 and current_time > self.shutdown_time and self.compressor_is_on:
            self.compressor_off()

        if not self.compressor_is_on:
            self._pause(MOTOR_STATE_OFF)
            return
        if self.purge_valve_open or self.purge_pending:
            self._pause(MOTOR_STATE_PURGE)
            return

        # If the tank sensor value is out of range then shut off the motor
        if self.tank_sensor_error:
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

    def _clean_up(self):
        # Make sure the motor isn't still running and the purge valve is closed,
        # since monitoring is about to stop
        self.compressor_motor.value(0)
        self.drain_solenoid.value(0)    

    async def _run_coroutine(self):
        print("WARNING: No watchdog timer in single thread mode. This is potentially dangerous.")

        self.running = True
        try:
            while self.running:                
                self._update()
                await asyncio.sleep(self.poll_interval)
        finally:
            self._clean_up()
            
        print("WARNING: Background coroutine loop has finished")
        
    def _run_thread(self):
        # Setup a watchdog timer to ensure that the compressor is always updated. If something
        # steals too many cycles the board will be rebooted rather than risk leaving the compressor
        # unattended.
        watchdog = WDT(timeout=5000)
        self.running = True
        if self.settings.debug_mode:
            h = HeartbeatMonitor('compressorLoop', self.poll_interval, memory_debug = True, histogram_bin_width = 5)
        
        try:
            while self.running:
                watchdog.feed()
                if self.settings.debug_mode:
                    h.update()
                
                with self.lock:
                    self._update()
                                
                # Put the thread to sleep
                time.sleep(self.poll_interval)
        finally:
            self._clean_up()
            
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
            self.run_task = asyncio.create_task(self._run_coroutine())
            
        if self.settings.compressor_on_power_up:
            self.compressor_on()
            
    def stop(self):
        self.running = False;
        # Clean up is called automatically when threads are aborted, but when
        # running coroutines it may be missed, so an explicity clean up will
        # ensure that the pins are set to low.
        self._clean_up()
