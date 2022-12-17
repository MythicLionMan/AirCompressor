from ringlog import RingLog
from condlock import CondLock
from heartbeatmonitor import HeartbeatMonitor
import debug

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
MOTOR_STATE_PRESSURE_CHANGE_ERROR=const('pressure_change_error') # The pressure didn't change when the motor started
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

        self.activity_log.console_log = settings.debug_mode & debug.DEBUG_EVENT_LOG
        self.command_log.console_log = settings.debug_mode & debug.DEBUG_ACTIVITY_LOG

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
        self.unload_valve_open = False   # True when the unload value is open, false when it is not
        self.purge_pending = False       # True when a purge is pending, false when it is not
        self.shutdown_time = 0           # The time when the compressor is scheduled to shutdown
        self.unload_close_time = 0       # The time when the unload valve is scheduled to close
        self.duty_recovery_time = 0      # The time when the motor will have recovered from the last duty cycle violation
        self.tank_pressure = None
        self.line_pressure = None
        self.tank_sensor_error = False   # The tank pressure sensor has detected an out of range value
        self.line_sensor_error = False   # The line pressure sensor has detected an out of range value
        self.pressure_change_error = False # The pressure has not started to increase soon enough after starting the motor
        self.running = False
        self.pressure_change_alert = None
                
        # Locate hardware registers
        self.tank_pressure_ADC = machine.ADC(settings.tank_pressure_pin)
        if settings.line_pressure_pin is not None:
            self.line_pressure_ADC = machine.ADC(settings.line_pressure_pin)
        else:
            self.line_pressure_ADC = None
            
        if settings.compressor_motor_pin is not None:
            self.compressor_motor = Pin(settings.compressor_motor_pin, Pin.OUT)
            # Ensure motor is stopped
            self.compressor_motor.value(0)
        else:
            self.compressor_motor = None

        if settings.unload_solenoid_pin is not None:
            self.unload_solenoid = Pin(settings.unload_solenoid_pin, Pin.OUT)
        else:
            self.unload_solenoid = None

        if settings.drain_solenoid_pin is not None:
            self.drain_solenoid = Pin(settings.drain_solenoid_pin, Pin.OUT)
            # Ensure that the drain valve is closed
            self.drain_solenoid.value(0)
        else:
            self.drain_solenoid = None
                    
        # Start an unload cycle in case the compressor was interrupted on the last run
        self._unload()
    
    def _read_ADC(self):
        if self.settings.debug_mode & debug.DEBUG_ADC_SIMULATE:
            if self.tank_pressure is None:
                self.tank_pressure = 90
            elif self.motor_state == MOTOR_STATE_RUN:
                self.tank_pressure = self.tank_pressure + 0.5
            else:
                self.tank_pressure = max(0, self.tank_pressure - 0.1)
            self.line_pressure = min(self.tank_pressure, 90)
        else:
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
                
        if self.settings.debug_mode & debug.DEBUG_ADC:
            if self.line_sensor_error and self.tank_sensor_error:
                print("both pressure sensors are reporting an error")
            elif self.line_sensor_error:
                print("line_pressure_sensor reporting an error")
            elif self.tank_sensor_error:
                print("tank_pressure_sensor reporting an error")
            
            if not self.tank_sensor_error or not self.tank_sensor_error:
                print("tank_pressure = " + str(self.tank_pressure) + " line_pressure = " + str(self.line_pressure))
            
    @property
    def _state_string(self):
        if self.motor_state == MOTOR_STATE_RUN:
            short_state = 'R'
        elif self.motor_state == MOTOR_STATE_OFF:
            short_state = 'f'
        elif self.motor_state == MOTOR_STATE_SENSOR_ERROR:
            short_state = 's'
        elif self.motor_state == MOTOR_STATE_PRESSURE_CHANGE_ERROR:
            short_state = '^'
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
            if self.pressure_change_alert:
                pressure_change_trend = self.pressure_change_alert.last_slope
            else:
                pressure_change_trend = None
            
            with self.settings.lock:
                start_pressure = self.settings.start_pressure
                min_line_pressure = self.settings.min_line_pressure
                duty_duration = self.settings.duty_duration
            
            total_runtime, log_start_time = self.activity_log.calculate_runtime()

            return {
                "system_time": time.time(),
                "tank_pressure": tank_pressure,
                "line_pressure": line_pressure,
                "tank_underpressure": tank_pressure < start_pressure,
                "line_underpressure": (tank_pressure < min_line_pressure) if line_sensor_error else\
                                      line_pressure < min_line_pressure,
                "tank_sensor_error": self.tank_sensor_error,
                "line_sensor_error": line_sensor_error,
                "pressure_change_error": self.pressure_change_error,
                "pressure_change_trend": pressure_change_trend,
                "compressor_on": self.compressor_is_on,
                "motor_state": self.motor_state,
                "run_request": self.request_run_flag,
                "purge_open": self.purge_valve_open,
                "purge_pending": self.purge_pending,
                "unload_open": self.unload_valve_open,
                "shutdown": self.shutdown_time,
                "duty_recovery_time": self.duty_recovery_time,
                "duty": self.activity_log.calculate_duty(duty_duration),
                "runtime": total_runtime,
                "log_start_time": log_start_time
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
                # Clear any alerts that were pending when the compressor ran last
                self._clear_conditions()

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
        if duration is None:
            duration = self.settings.drain_duration
        if delay is None:
            delay = self.settings.drain_delay
            
        self.purge_task = asyncio.create_task(self._purge(duration, delay))

    # NOTE: Unlike most private Compressor methods, this runs as a coroutine
    #       On the foreground thread, not on the background thread. Thus it
    #       must aquire a lock before performing any compressor specific actions
    async def _purge(self, duration, delay):
        if duration > 0 and self.drain_solenoid is not None:
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
        if self.drain_solenoid is not None:
            self.drain_solenoid.value(0)
        if self.compressor_motor is None:
            return
            
        self.compressor_motor.value(1)
        
        if self.motor_state != MOTOR_STATE_RUN:
            self.motor_state = MOTOR_STATE_RUN
            self.activity_log.log_start(compressorlogs.EVENT_RUN)
            self._monitor_for_pressure_change()

    def _monitor_for_pressure_change(self):
        pressure_change_duration = self.settings.pressure_change_duration
        if self.pressure_change_alert == None and pressure_change_duration > 0:
            self.pressure_change_alert = PressureChangeAlert(self.state_log, pressure_change_duration, self.settings.detect_pressure_change_threshold)

    # Clears any conditions or alerts that were set the last time that the compressor ran
    def _clear_conditions(self):
        # If there is a stored pressure_change_error, clear it
        self.pressure_change_error = False
        # A side effect of restarting the compressor is clearing the duty recovery time
        # This is intended to provide an easy way to clear a duty recovery timer when needed
        # (it's a feature, not a bug)
        self.duty_recovery_time = 0
                
    def _should_pause(self, current_time, max_duty, current_duty):
        if not self.compressor_is_on:
            # Dont run the motor if the compressor is off (in other words, if it is not maintaining pressure)
            self.request_run_flag = False
            return MOTOR_STATE_OFF
        if self.purge_valve_open or self.purge_pending:
            # Dont run the motor if the purge valve is open
            return MOTOR_STATE_PURGE

        if self.pressure_change_alert:
            try:
                # If the alert has expired, cancel it
                if self.pressure_change_alert.update():
                    self.pressure_change_alert = None
            except PressureChangeAlertError as err:
                self.pressure_change_alert = None
                self.pressure_change_error = True
                
        if self.pressure_change_error:
            return MOTOR_STATE_PRESSURE_CHANGE_ERROR
        
        # If the tank sensor value is out of range then shut off the motor
        if self.tank_sensor_error:
            return MOTOR_STATE_SENSOR_ERROR
                        
        if current_time < self.duty_recovery_time:
            return MOTOR_STATE_DUTY
        
        if max_duty < 1 and current_duty > max_duty:
            # If the motor is currently running trigger a request to run again once
            # the duty cycle condition is cleared
            self.request_run_flag = self.request_run_flag or self.motor_state == MOTOR_STATE_RUN

            # TODO recovery_time could be calculated by averaging (or taking the  max) of the last few
            #      run cycles. For now it's just a setting
            self.duty_recovery_time = current_time + self.settings.recovery_time
            # TODO If we have a 'next' compressor we could pass them a duty token
            #      so that they run, and disable self so that we do not. This isn't the
            #      best approach to load balancing though, so more thought is be required
            return MOTOR_STATE_DUTY
        
        return None
                
    def pause(self):
        with self.lock:
            self.command_log.log_command(compressorlogs.COMMAND_PAUSE)
            self._pause(MOTOR_STATE_PAUSE)
        
    def _pause(self, reason):
        if self.compressor_motor is not None:
            self.compressor_motor.value(0)
            self.activity_log.log_stop()
            if self.motor_state == MOTOR_STATE_RUN:
                # If there was a pressure_change_alert it will not be valid when the motor starts up again.
                # Clear it now.
                self.pressure_change_alert = None
                # Start an unload cycle
                self._unload()
            self.motor_state = reason
        
    # Unlike purging (which is slightly more complex) unloading is handled directly by the update loop.
    # Unloading is a critical operation, since motor damage could result if the unload valve fails to open.
    def _unload(self):
        print("Unload")
        if self.unload_solenoid is not None:
            self.unload_valve_open = True
            self.unload_solenoid.value(1)
            self.unload_close_time = time.time() + self.settings.unload_duration
            
    def _stop_unload(self):
        print("Stop Unload")
        if self.unload_solenoid is not None:
            self.unload_valve_open = False
            self.unload_solenoid.value(0)

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
        
        # If it is time to close the unload valve do so
        if current_time > self.unload_close_time and self.unload_valve_open:
            self._stop_unload()
        
        # If the auto shutdown time has arrived schedule a shutdown task
        if self.shutdown_time > 0 and current_time > self.shutdown_time and self.compressor_is_on:
            self.compressor_off()

        # If the pressure limit has been reached turn off request_run,
        # even if the compressor has not run.
        if current_pressure > self.settings.stop_pressure:
            self.request_run_flag = False

        # Before controlling the motor check to see if there is a reason that the compressor should be paused
        pause_reason = self._should_pause(current_time, max_duty, current_duty)
        if pause_reason is not None:
            self._pause(pause_reason)
            return

        if current_pressure > self.settings.stop_pressure:
            self._pause(MOTOR_STATE_PRESSURE)
        elif current_pressure < self.settings.start_pressure or self.request_run_flag:
            self.request_run_flag = False
            self._run_motor()

    def _clean_up(self):
        # Make sure the motor isn't still running and the purge valve is closed,
        # since monitoring is about to stop
        if self.compressor_motor is not None:
            self.compressor_motor.value(0)
        if self.drain_solenoid is not None:
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
        if self.settings.debug_mode & debug.DEBUG_THREADS:
            h = HeartbeatMonitor('compressorLoop', self.poll_interval, memory_debug = True, histogram_bin_width = 5)
        
        try:
            while self.running:
                watchdog.feed()
                if self.settings.debug_mode & debug.DEBUG_THREADS:
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

class PressureChangeAlertError(Exception):
    pass
    
class PressureChangeAlert:
    def __init__(self, state_log, duration, target_pressure_change):
        self.state_log = state_log
        
        try:
            self.start_time = time.time()
            self.error_time = self.start_time + duration
            # Find the pressure slope up to this time
            # TODO This result is only valid if we have more than few samples. There should be a threshold on the number of samples.
            (self.last_slope, b) = self.state_log.linear_least_squares(start_time = self.start_time - duration)
            # The target slope is the current slope (which accounts for any current load) plus the required
            # change in value.
            self.target_pressure_change = self.last_slope + target_pressure_change
        except ZeroDivisionError as err:
            print("Zero division calculating linear_least_squares")
            # The current rate of change couldn't be determined. Set the target based on an asumed rate of change of 0
            # (Since the pressure chould not be increasing at the current time, this makes for a stricter requirement,
            # since any loss due to a load will not be included in the target)
            self.target_pressure_change = target_pressure_change
            self.last_slope = 0
            
    def update(self):
        current_time = time.time()
        if current_time >= self.error_time:
            print("PressureChangeAlert() has expired without detecting pressure change at time {} after {} seconds. Rasing an exception.".format(current_time, current_time - self.start_time))
            raise PressureChangeAlertError()
        
        try:
            # Find the pressure slope since the alert was created
            # TODO This result is only valid if we have more than few samples. There should be a threshold on the number of samples.
            (self.last_slope, b) = self.state_log.linear_least_squares(start_time = self.start_time)
            
            if self.last_slope >= self.target_pressure_change:
                print("PressureChangeAlert() pressure slope = {} threshold {} reached, cancelling alert".format(self.last_slope, self.target_pressure_change))
                return True
            else:
                print("PressureChangeAlert() pressure slope = {} threshold {} not reached, continuing to monitor".format(self.last_slope, self.target_pressure_change))
        except ZeroDivisionError as err:
            print("Zero division calculating linear_least_squares")
        
        return False
