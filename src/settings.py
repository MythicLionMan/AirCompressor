import ujson
from condlock import CondLock

# Settings manages persistent settings, and attempts to minimize the amount
# of data that must be written. When settings are persisted they are written
# to a JSON file that contains only the settings that are different than the
# default values. Not only does this minimize Flash RAM erases, it also allows
# the default values to be updated in the future without being overwritten by
# saved default values.
#
# The defaults array supplies default values. For settings that are represented
# by simple types that can be serialized directly as json, supplying the value in
# defaults is sufficient to initialize the value. For more complex types, the
# derived class must intialize the value type in setup_properties() in order to 
# specify the type of the object.
#
# Settings can be run in thread_safe mode. In thread_safe mode it will aquire lock
# before updating or returning settings, so settings can accessed from mulitple
# threads without contention. Note that if multiple values are read, it is still the
# callers responsability to ensure that proper locking is used to ensure that they are
# consistent. It is possible for a caller to aquire settings.lock to ensure that
# settings are not mutated between queries.
class Settings:
    def __init__(self, defaults, persist_path = 'settings.json', thread_safe = False):
        self.defaults = defaults
        self.values = {}
        self.private_keys = ()
        self.persist_path = persist_path
        self.lock = CondLock(thread_safe)
        
        # Create the ValueScale settings
        self.setup_properties(defaults)
                
        # Read the saved settings. This will populate the properties of self
        # even if there are no saved settings
        self._read()
        
    def __getattr__(self, name):
        with self.lock:
            return self.values[name]
    
    @property
    def values_dictionary(self):
        with self.lock:
            return {k: (v.values_dictionary if isinstance(v, Settings) else v) for (k, v) in self.values.items()}
    
    @property
    def public_values_dictionary(self):
        with self.lock:
            values = self.values_dictionary
            for key in self.private_keys:
                values.pop(key, None)
            return values
    
    def setup_properties(self, defaults):
        pass
    
    # Returns a dictionary of the keys of self that are different from the default values
    @property
    def delta(self):
        with self.lock:
            delta = {}
            defaults = self.defaults
            
            for key, default_value in self.defaults.items():
                # Find the current value of the object
                current_value = self.values[key]
                # If the existing value is another Settings object, recurse into it
                if isinstance(current_value, Settings):
                    delta_values = current_value.delta
                    
                    # If the sub object had deltas assign them to the result
                    if len(delta_values) > 0:
                        delta[key] = delta_values
                else:
                    if defaults[key] != current_value:
                        delta[key] = current_value
                        
            return delta

    # Writes the values of self to permanent storage. Only values that are
    # different from the defaults are written. Writing should be minimized
    # to preserve the flash RAM, so only perform a single write when all
    # updates in a batch are complete.
    def write_delta(self):
        if self.persist_path != None:
            delta = ujson.dumps(self.delta)
            f = open(self.persist_path, 'w')
            f.write(delta)
            f.close()
            
    # Updates the values of self using a dictionary
    def update(self, values):
        with self.lock:
            defaults = self.defaults
            current_values = self.values

            for key, new_value in values.items():
                if key in defaults:
                    if key in self.values:
                        # Find the current value of the object
                        current_value = current_values[key]
                        default_value = defaults[key]
                        
                        # If the existing value is another settings object, recurse into it
                        if isinstance(current_value, Settings):
                            current_value.update(new_value)
                        # Otherwise assign the new value, matching the type of the default value
                        elif isinstance(current_value, float):
                            self.values[key] = float(new_value)
                        elif isinstance(current_value, int):
                            self.values[key] = int(new_value)
                        elif isinstance(current_value, str):
                            self.values[key] = str(new_value)
                        elif isinstance(current_value, bool):
                            self.values[key] = bool(new_value in ['true', 'True'])
                        else:
                            self.values[key] = new_value
                    else:
                        self.values[key] = new_value
                        
    # Updates the values of self from the defaults, and then tries to open a settings
    # difference file. If one is found its settings are applied on top of the defaults.
    def _read(self):
        # Restore the default values
        self.update(self.defaults)

        if self.persist_path != None:
            try:
                f = open(self.persist_path)
                delta = f.read()
                f.close()
                # Read any values that have been persisted and apply them on top of the defaults
                values = ujson.loads(delta)
                self.update(values)
            except OSError:
                print("Could not find settings file at " + self.persist_path)
        
class ValueScale(Settings):
    def __init__(self, defaults):
        super().__init__(defaults, None)
        
    def map(self, raw_value):
        # Accessing the individual values are protected by the lock, but
        # to ensure that they are all consistent wrap the entire operation
        # in a lock to ensure an update doesn't change some of them
        # concurrently
        with self.lock:
            sensor_min = self.sensor_min
            sensor_max = self.sensor_max
            value_min = self.value_min
            sensor_range = self.sensor_range
            value_range = self.value_range
            
            if raw_value < sensor_min or raw_value > sensor_max:
                return None
                
            scaled = (raw_value - sensor_min)/sensor_range
            return scaled*value_range + value_min
                    
    # Updates the values of self using a dictionary, and returns the values that are
    # not the same as the defaults
    def update(self, values):
        # Aquire a lock to ensure that the values are updated atomically
        # with performing the update
        with self.lock:
            super().update(values)

            # Calculate the ranges from the limits
            self.sensor_range = self.sensor_max - self.sensor_min
            self.value_range = self.value_max - self.value_min
