import ujson

        
# Settings manages persistent settings, and attempts to minimize the amount
# of data that must be written. When settings are persisted they are written
# to a JSON file that contains only the settings that are different than the
# default values. Not only does this minimize Flash RAM erases, it also allows
# the default values to be updated in the future without being overwritten by
# saved settings.
#
# The defaults array supplies default values. For settings that are represented
# by simple types that can be serialized directly as json, supplying the value in
# defaults is sufficient to initialize the value. For more complex types, the
# derived class must intialize the value type in setup_properties() in order to 
# specify the type of the object.
class Settings:
    def __init__(self, defaults, persist_path = 'settings.json'):
        self.defaults = defaults
        self.values = {}
        self.persist_path = persist_path
        
        # Create the ValueScale settings
        self.setup_properties(defaults)
                
        # Read the saved settings. This will populate the properties of self
        # even if there are no saved settings
        self._read()
        
    def __getattr__(self, name):
        return self.values[name]

    def setup_properties(self, defaults):
        pass
    
    # Returns a dictionary of the keys of self that are different from the default values
    @property
    def delta(self):
        delta = {}
        defaults = self.defaults
        
        for key, default_value in self.defaults.items():
            # Find the current value of the object
            current_value = self.values[key]
            # If the existing value supports the update method, recurse into it
            delta_method = getattr(current_value, "delta", None)
            if callable(delta_method):
                delta_values = delta_method(current_value, default_value)
                
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
        defaults = self.defaults
        current_values = self.values

        for key, new_value in values.items():
            if key in defaults:
                if key in self.values:
                    # Find the current value of the object
                    current_value = current_values[key]
                    default_value = defaults[key]
                    
                    # If the existing value supports the update method, recurse into it
                    update_method = getattr(current_value, "update", None)
                    if callable(update_method):
                        update_method(new_value)
                    # Otherwise assign the new value, matching the type of the default value
                    elif isinstance(current_value, float):
                        self.values[key] = float(new_value)
                    elif isinstance(current_value, int):
                        self.values[key] = int(new_value)
                    elif isinstance(current_value, str):
                        self.values[key] = str(new_value)
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
        if raw_value < self.sensor_min or raw_value > self.sensor_max:
            return None
            
        scaled = (raw_value - self.sensor_min)/self.sensor_range
        return scaled*self.value_range + self.value_min
                    
    # Updates the values of self using a dictionary, and returns the values that are
    # not the same as the defaults
    def update(self, values):
        super().update(values)

        # Calculate the ranges from the limits
        self.sensor_range = self.sensor_max - self.sensor_min
        self.value_range = self.value_max - self.value_min
        