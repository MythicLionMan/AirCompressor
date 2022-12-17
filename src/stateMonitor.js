class StateMonitor {
    constructor(lastUpdateTimeId, tankPressureGauge, linePressureGauge, dutyGraph) {
        this.monitorId = null;
        this.server_time_offset = null;
        this.fetchPending = new FetchLock(settings.fetchRecoveryInterval);
        
        this.lastUpdateTimeElement = lastUpdateTimeId ? document.getElementById(lastUpdateTimeId) : null;
        this.stateElements = Array.from(document.getElementsByClassName('undefined_state'));
        
        var tankPressureCanvas = document.getElementById(tankPressureGauge);
        if (tankPressureCanvas) {
            this.tankPressureGauge = new Gauge(tankPressureCanvas, 'Tank Pressure');
            this.tankPressureGauge.draw();
        }
        var linePressureCanvas = document.getElementById(linePressureGauge);
        if (linePressureCanvas) {
            this.linePressureGauge = new Gauge(linePressureCanvas, 'Line Pressure');
            this.linePressureGauge.draw();
        }
        var dutyGraphCanvas = document.getElementById(dutyGraph);
        if (dutyGraphCanvas) {
            this.dutyGraphCanvas = new PieChart(dutyGraphCanvas, 'Duty');
            this.dutyGraphCanvas.draw();
        }
    }
    
    // Begins periodically polling the server for the state of self
    monitor(interval = null) {
        interval ??= settings.stateQueryInterval;
        
        let t = this;
        if (interval == 0) {
            if (this.monitorId) {
                clearInterval(this.monitorId);
                this.monitorId = null;
            }
        } else if (settings.debug) {
            this.monitorId = setInterval(() => t.applyDebugState(), interval);
            this.applyDebugState();
        } else {
            this.monitorId = setInterval(() => t.fetchState(), interval);
            this.fetchState();
        }
    }
        
    applyDebugState() {
        this.updateState({
            'system_time': Date.now() / 1000,
            'tank_pressure': 110 + Math.random() * 20,
            'line_pressure': 80 + Math.random() * 20,
            'duty': Math.random(),
            'runtime': Math.random()*60*60*4,
            'log_start_time': Date.now() / 1000 - 60*60*4,
            'compressor_on': true,
            'run_request': false,
            'tank_underpressure': false,
            'line_underpressure': false,
            'tank_sensor_error': false,
            'line_sensor_error': false,
            'pressure_change_trend': 0,
            'motor_state': 'run',
            'purge_open': true,
            'purge_pending': false,
            'shutdown': Date.now() / 1000 + 60*60*5,
            'duty_recovery_time': Date.now() / 1000 + 60*2,
            'max_duty': 0.6,
            'recovery_time': 60*2
        });
    }
    
    // Updates the state of the document based on a json state description
    // received from the server. Derived classes may overload this method
    // to disable default functionality, or to extend it.
    updateState(state) {
        this.updateHTMLWithCompressorState(state);
        this.updateClassesWithCompressorState(state);
    }

    // Updates the document HTML with a state dictionary by assigning values
    // to the html element with the same key.
    updateHTMLWithCompressorState(state) {
        // Copy the state data to the html elements whose id matches
        // the keys fetched in the state dictionary
        for (const [key, value] of Object.entries(state)) {
            let element = document.getElementById(key);
            if (element) {
                element.innerHTML = this.map(key, value);
            }
        };
        
        if (this.tankPressureGauge) {
            this.tankPressureGauge.value = state.tank_pressure;
            if (settings.debug) {
                this.tankPressureGauge.startPressure = 90;
                this.tankPressureGauge.stopPressure = 120;
            }
            this.tankPressureGauge.draw();
        }
        
        if (this.linePressureGauge) {
            this.linePressureGauge.value = state.line_pressure;
            if (settings.debug) {
                this.linePressureGauge.alarmPressure = 80;
            }
            this.linePressureGauge.draw();
        }
        
        if (this.dutyGraphCanvas) {
            this.dutyGraphCanvas.value = state.duty;
            this.dutyGraphCanvas.maxDuty = state.max_duty;
            this.dutyGraphCanvas.draw();
        }
    }

    // Maps a state value from the json state definition to an HTML value.
    // Derived classes can overload this to provide a different mapping.
    map(key, value) {
        if (key == 'system_time' || key == 'log_start_time') {
            value = new Date(value * 1000 - this.server_time_offset);
            return value.toLocaleTimeString();
        } else if (key == 'runtime') {
            value = Math.round(value);
            var hours   = Math.floor(value / 3600);
            var minutes = Math.floor((value - (hours * 3600)) / 60);
            var seconds = value - (hours * 3600) - (minutes * 60);

            if (hours   < 10) { hours   = "0"+hours; }
            if (minutes < 10) { minutes = "0"+minutes; }
            if (seconds < 10) { seconds = "0"+seconds; }
            return hours + ':' + minutes + ':' + seconds;
        } else if (key == 'shutdown' || key == 'duty_recovery_time') {
            // A value of 0 means that the time is not set
            if (value == 0) {
                return 'never';
            }

            value = new Date(value * 1000 - this.server_time_offset);
            return value.toLocaleTimeString();
        } else if (key == 'duty') {
            return Math.round(value * 100).toString() + '%';
        } else if (key == 'tank_pressure' || key == 'line_pressure') {
            return value.toFixed(2);
        } else if (key == 'pressure_change_trend') {
            if (value == null) {
                return '';
            } else {
                return value.toFixed(3);
            }
        }
        return value;
    }

    removeStateClass(stateName) {
        for (let element of this.stateElements) {
            element.classList.remove(stateName);
        }
    }

    addStateClass(stateName) {
        for (let element of this.stateElements) {
            element.classList.add(stateName);
        }
    }
    
    // Updates the html classes that are assigned to elements with a state
    // class.
    updateClassesWithCompressorState(state) {
        let booleanStateClassNames = [
            'compressor_on', 'run_request', 'purge_pending', 'purge_open',
            'tank_underpressure', 'line_underpressure', 'tank_sensor_error',
            'line_sensor_error', 'pressure_change_error'
        ];

        // Calculate some extra compound states that are difficult or impossible in css
        let addStates = []
        let removeStates = []
        if ('tank_underpressure' in state) {
            // Cannot pause or run if the tank is not in its target pressure range
            removeStates.push('pause_command_available');
            removeStates.push('run_command_available');
        } else {
            if (state.motor_state == 'run') {
                addStates.push('pause_command_available');
            } else {
                removeStates.push('pause_command_available');
            }

            if (Set(['pause', 'overpressure', 'duty']).has(state.motor_state)) {
                addStates.push('run_command_available');
            } else {
                removeStates.push('run_command_available');
            }
        }
        
        for (let element of this.stateElements) {
            element.classList.remove('undefined_state');
            for (const className of booleanStateClassNames) {
                if (state[className]) {
                    element.classList.add(className);
                } else {
                    element.classList.remove(className);
                }
            }
            for (const className of addStates) {
                element.classList.add(className);
            }
            for (const className of removeStates) {
                element.classList.remove(className);
            }
        }
        
        // Add the new motor state and remove any previous motor states
        const motorState = 'motor_state_' + state['motor_state'];
        for (let element of this.stateElements) {
            // Remove any previous motorState classes from the element
            var motorClasses = Array.from(element.classList).filter(className => className.startsWith('motor_state_'));
            for (let foundClass of motorClasses) {
                if (foundClass != motorState) {
                    element.classList.remove(foundClass);
                }
            }
            
            // Add the current motorState class
            element.classList.add(motorState);
        }
    }
        
    synchronizeTime(data) {
        if (this.server_time_offset === null) {
            this.server_time_offset = data['system_time'] * 1000 - Date.now();
            console.log('StateMonitor.sever_time_offset = ' + this.server_time_offset.toString());
        }
    }

    // Initiates a fetch and handles the result
    fetchState() {
        if (this.fetchPending.isLocked()) {
            // The last fetch is still pending, so don't start a new one
            return;
        }
        let t = this;
        // Show an alert if we don't hear from this fetch in a timely fashion
        this.fetchLate = setTimeout(() => t.fetchLateHandler(), settings.stateFetchLateInterval);
                
        // Query the server
        fetch('/status', {
           method: 'GET',
           headers: {
               'Accept': 'application/json',
           }
        })
        .then((response) => response.json())
        .then((data) => t.handleFetchStateResponse(data))
        .catch((error) => t.handleFetchStateError(error))
        .finally(() => t.fetchPending.unlock());
    }
    
    fetchLateHandler() {
        this.fetchLate = null;
        this.handleFetchStateError('State fetch overdue.');
    }
    
    handleFetchStateResponse(data) {
        // Cancel any pending fetchLate watchdog
        if (this.fetchLate) {
            clearTimeout(this.fetchLate);
            this.fetchLate = null;
        }
        
        this.removeStateClass('compressor_error');
        
        // Update the time when the last succesful update was received
        if (this.lastUpdateTimeElement) {
            const now = new Date();
            this.lastUpdateTimeElement.innerHTML = now.toLocaleTimeString();
        }

        this.synchronizeTime(data);
        this.updateState(data);
    }
    
    handleFetchStateError(error) {
        console.error('Communication Error: ', error);
        this.addStateClass('compressor_error');
    }
}
