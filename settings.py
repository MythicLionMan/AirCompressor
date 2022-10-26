import ujson

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
    
    @property
    def delta(self):
        delta = {}
        defaults = self.defaults
        
        for key, value in self.dictionary_representation.items():
            if defaults[key] != value:
                delta[key] = value
                                    
        return delta
        
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
        
# Settings manages persistent settings, and attempts to minimize the amount
# of data that must be written. When settings are persisted they are written
# to a JSON file that contains only the settings that are different than the
# default values. Not only does this minimize Flash RAM erases, it also allows
# the default values to be updated in the future without being overwritten by
# saved settings.
class Settings:
    def __init__(self, defaults, persist_path = 'settings.json'):
        self.defaults = defaults
        self.persist_path = persist_path
        
        # Create the ValueScale settings
        self.tank_pressure = ValueScale(defaults["tank_pressure_sensor"])
        self.line_pressure = ValueScale(defaults["line_pressure_sensor"])
                
        # Read the saved settings. This will populate the properties of self
        # even if there are no saved settings
        self._read()
        
    @property
    def dictionary_representation(self):
        return {
            "start_pressure": self.start_pressure,
            "stop_pressure": self.stop_pressure,
            "max_duty": self.max_duty,
            "duty_duration": self.duty_duration,
            "recovery_time": self.recovery_time,
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

    # Returns a dictionary of the keys of self that are different from the default values
    @property
    def delta(self):
        delta = {}
        defaults = self.defaults
        
        for key, value in self.dictionary_representation.items():
            if key == "tank_pressure_sensor":
                delta[key] = self.tank_pressure.delta
            elif key == "line_pressure_sensor":
                delta[key] = self.line_pressure.delta
            else:
                if defaults[key] != value:
                    delta[key] = value
                    
        return delta

    # Writes the values of self that are different than the 
    # values to permanent storage. Only values that are different from the defaults
    # are written. Writing should be minimized to preserve the flash RAM,
    # so only perform a write when all updates have been performed.
    def write_delta(self):
        delta = ujson.dumps(self.delta)
        f = open(self.persist_path, 'w')
        f.write(delta)
        f.close()
            
    # Updates the values of self using a dictionary
    def update(self, values):
        defaults = self.defaults
        
        for key, value in values.items():
            if key == "tank_pressure_sensor":
                self.tank_pressure.update(value)
            elif key == "line_pressure_sensor":
                self.line_pressure.update(value)
            else:
                if key == "start_pressure":
                    self.start_pressure = int(value)
                elif key == "stop_pressure":
                    self.stop_pressure = int(value)
                elif key == "max_duty":
                    self.max_duty = float(value)
                elif key == "duty_duration":
                    self.duty_duration = int(value)
                elif key == "recovery_time":
                    self.recovery_time = int(value)
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
                        
    # Updates the values of self from the defaults, and then tries to open a settings
    # difference file. If one is found its settings are applied on top of the defaults.
    def _read(self):
        # Restore the default values
        self.update(self.defaults)

        try:
            f = open(self.persist_path)
            delta = f.read()
            f.close()
        
            # Read any values that have been persisted and apply them on top of the defaults
            values = ujson.loads(delta)
            self.update(values)
        except OSError:
            print("Could not find settings file at " + self.persist_path)
            # If there are no persisted settings just move on
            pass
