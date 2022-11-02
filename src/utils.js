settings = {
    stateQueryInterval: 5000,
    chartQueryInterval: 5000,
    chartDuration: [ 5*60*1000, 10*60*1000, 20*60*1000 ]
};

class CompressorActions {
    constructor(stateMonitor) {
        this.stateMonitor = stateMonitor;
    }
    
    submitSettings(formID) {
        // Convert the form to json
        const formData = new FormData(document.getElementById(formID))
        let data = {};
        formData.forEach((value, key) => data[key] = value);
                
        this.submitToEndpoint('POST', '/settings', data)
    }
    
    turnOn() {
        this.submitToEndpoint('GET', '/on')
    }

    turnOff() {
        this.submitToEndpoint('GET', '/off')
    }

    pause() {
        this.submitToEndpoint('GET', '/pause')
    }

    run() {
        this.submitToEndpoint('GET', '/run')
    }

    purge() {
        this.submitToEndpoint('GET', '/purge')    
    }
    
    submitToEndpoint(method, endpoint, bodyData) {
        var body = null;
        if (bodyData) {
            body = JSON.stringify(bodyData);
        }
        
        // Submit to the server
        fetch(endpoint, {
           method: method, 
           headers: {
               'Accept': 'application/json',
               'Content-Type': 'application/json'
           },
           body: body
        })
        .then((response) => response.json())
        .then((data) => {
           if (data['result'] == 'ok') {
               this.callSuccess(endpoint);
           } else {
               console.log('Error updating remote')       
               this.callFailure(endpoint);
           }
        })
        .catch((error) => {
           console.error('Communication Error:', error);
           this.callFailure(endpoint);
        });
    }
    
    callSuccess(endpoint) {
        const messages = {
            "/settings": 'Settings Updated'
        }
            
        this.success(endpoint, messages[endpoint]);
        // Refetch the state to update the UI
        this.stateMonitor.fetchState();
    }
    
    callFailure(endpoint) {
        const messages = {
            "/settings": 'Compressor rejected settings',
            "/on": 'Compressor did not turn on',
            "/off": 'Compressor did not turn off',
            "/run": 'Compressor did not run',
            "/pause": 'Compressor did not pause',
            "/purge": 'Compressor did not purge'
        }
        this.failure(endpoint, messages[endpoint]);
    }
    
    // Derived classes can overload this method to show the message differently
    success(endpoint, message) {
        if (message) {
            alert(message);
        }
    }

    // Derived classes can overload this method to show the error differently
    failure(endpoint, message) {
        if (message) {
            alert(message);
        }
    }    
}

class StateMonitor {
    constructor(errorId) {
        this.monitorId = null;
        this.errorId = errorId;
        this.errorOriginalHTML = null;
    }
    
    // Begins periodically polling the server for the state of self
    monitor(interval = null) {
        if (interval === null) { interval = settings.stateQueryInterval; }
        
        if (interval == 0) {
            if (this.monitorId) {
                clearInterval(this.monitorId);
                this.monitorId = null;
            }
        } else {
            let t = this;
            this.monitorId = setInterval(function(){t.fetchState();}, interval);
        }
    }
    
    // Updates the state of the document based on a json state description
    // received from the server. Derived classes may overload this method
    // to disable default functionality, or to extend it.
    updateState(state) {
        this.updateHTMLWithCompressorState(state);
        this.updateButtonsWithCompressorState(state);
    }

    // Updates the document HTML with a state dictionary by assigning values
    // to the html element with the same key.
    updateHTMLWithCompressorState(state) {
        // Copy the state data to the html elements whose id matches
        // the keys fetched in the state dictionary
        for (const [key, value] of Object.entries(state)) {        
            let element = document.getElementById(key);
            if (element) element.innerHTML = this.map(key, value);
        };
    }
    
    // Hides/shows buttons based on a state dictionary. Derived classes may 
    // overload this method to control how buttons are configured.
    updateButtonsWithCompressorState(state) {
        document.getElementById('on_button').hidden = state.compressor_on;
        document.getElementById('off_button').hidden = !state.compressor_on;
        document.getElementById('pause_button').hidden = !state.compressor_motor_running;
        document.getElementById('run_button').hidden = state.compressor_motor_running;
        document.getElementById('purge_button').hidden = state.compressor_motor_running;
    }
    
    // Maps a state value from the json state definition to an HTML value.
    // Derived classes can overload this to provide a different mapping.
    map(key, value) {
        return value;
    }

    // Initiates a fetch and calls updateState with the result
    fetchState() {
        // Query the server
        fetch('/status', {
           method: 'GET', 
           headers: {
               'Accept': 'application/json',
           }
        })
        .then((response) => response.json())
        .then((data) => {
            this.clearError();
            this.updateState(data);
        })
        .catch((error) => {
           console.error('Communication Error:', error);
           this.displayError(error);
        });
    }
    
    clearError() {
        if (this.errorId) {
            let element = document.getElementById(this.errorId);
            if (!element.hidden && this.errorOriginalHTML) {
                element.hidden = true;
                element.innerHTML = this.errorOriginalHTML;
                this.errorOriginalHTML = null;
            }
        }
    }
    
    displayError(error) {
        if (this.errorId) {
            let element = document.getElementById(this.errorId);
            
            if (element.hidden) {
                this.errorOriginalHTML = element.innerHTML;
                const now = Date();
                element.innerHTML = this.errorOriginalHTML + now.toLocaleString();
                element.hidden = false;
            }
        }
    }
}

class ChartMonitor {
    constructor(chartId) {
        this.monitorId = null;
        this.chart = null;

        this.last_state_update = 0;
        this.last_activity_update = 0;
        this.server_time_offset = null;

        this.activitiesVisible = true;
        this.commandsVisible = true;

        this.setChartDurationIndex(0);

        if (document.readyState === 'complete') {
            this.chart = configureChart(document.getElementById(chartId).getContext('2d'));
        } else {
            console.log('Document is not ready, scheduling chart setup when page is loaded.');
            let t = this;
            window.onload = function() {
                t.configureChart(document.getElementById(chartId).getContext('2d'));
            }
        }
    }

    monitor(chartId, interval = null) {
        if (interval === null) { interval = settings.chartQueryInterval; }
    
        if (interval == 0) {
            if (this.monitorId) {
                clearInterval(this.monitorId);
                this.monitorId = null;
            }
        } else {
            let t = this;
            this.monitorId = setInterval(function(){ t.updateChart() }, interval);
        }
    }

    setChartDurationIndex(index) {
        if (this.chartDurationIndex != index) {
            this.chartDuration = settings.chartDuration[index];
            this.chartDurationIndex = index;
            
            if (this.chart) {
                this.updateDomain();
                this.chart.update();
            }
        }
    }
        
    setSeriesVisibility(visible, index) {
        this.chart.setDatasetVisibility(index, visible);
        this.chart.update()        
    }
    
    setActivityVisibility(visible) {
        this.activitiesVisible = visible;

        // Update existing activity annotations
        for (const [key, annotation] of Object.entries(this.chart.options.plugins.annotation.annotations)) {
            if (key.startsWith('activity_id_')) {
                annotation.display = visible;
            }
        };
        this.chart.update();
    }
    
    setCommandVisibility(visible) {
        this.commandsVisible = visible;
        
        // Update existing command annotations
        for (const [key, annotation] of Object.entries(this.chart.options.plugins.annotation.annotations)) {
            if (key.startsWith('command_id_')) {
                annotation.display = visible;
            }
        };
        this.chart.update();
    }
    
    getDutyGradient(ctx, chartArea) {
        const chartWidth = chartArea.right - chartArea.left;
        const chartHeight = chartArea.bottom - chartArea.top;
        if (!this.dutyGradient || this.dutyGradientWidth !== chartWidth || this.dutyGradientHeight !== chartHeight) {
            // Create the gradient because this is either the first render
            // or the size of the chart has changed
            this.dutyGradientWidth = chartWidth;
            this.dutyGradientHeight = chartHeight;
            
            this.dutyGradient = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top);
            this.dutyGradient.addColorStop(0, 'rgb(75, 192, 192)');
            this.dutyGradient.addColorStop(1, 'rgb(255, 99, 132)');
        }

        return this.dutyGradient;
    }

    configureChart(ctx) {
        console.log('Document is ready, setting up chart');

        // All of the state data will be appended to this array
        this.stateData = [];
        
        let t = this;
        this.chart = new Chart(ctx, {
            type: 'scatter',
            data: {
                datasets: [{
                    label: 'Tank Pressure',
                    showLine: true,
                    data: this.stateData,
                    parsing: {
                        yAxisKey: 'tank_pressure',
                    },
                    tooltip: {
                        callbacks: { label: function(context) { return context.dataset.label + ' ' + context.parsed.y + ' PSI'; } }
                    },
                    yAxisID: 'pressure',
                    borderColor: '#FF0000'
                },{
                    label: 'Line Pressure',
                    showLine: true,
                    data: this.stateData,
                    parsing: {
                        yAxisKey: 'line_pressure',
                    },
                    tooltip: {
                        callbacks: { label: function(context) { return context.dataset.label + ' ' + context.parsed.y + ' PSI'; } }
                    },
                    yAxisID: 'pressure',
                    borderColor: '#FFFF00'
                },{
                    label: 'Duty',
                    showLine: true,
                    data: this.stateData,
                    parsing: {
                        yAxisKey: 'duty',
                    },
                    tooltip: {
                        callbacks: { label: function(context) { return context.dataset.label + ' ' + context.parsed.y + '%'; } }
                    },
                    yAxisID: 'percent',
                    borderColor: function(context) {
                        const chart = context.chart;
                        const {ctx, chartArea} = chart;

                        if (!chartArea) {
                          // This case happens on initial chart load
                          return;
                        }
                        return t.getDutyGradient(ctx, chartArea);
                    },
                }]
            },
            options: {
                elements: {
                    point: {
                        radius: 0
                    }
                },
                parsing: {
                    xAxisKey: 'time'
                },
                //animation: {
                //    duration: settings.chartQueryInterval,
                //    easing: 'linear'
                //},
                scales: {
                    pressure: {
                        type: 'linear',
                        display: true,
                        position: 'left',
                        min: 0,
                        max: 150,
                        title: {
                            display: true,
                            text: 'Pounds per Square Inch'
                        }
                    },
                    percent: {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        min: 0,
                        max: 100,

                        // grid line settings
                        grid: {
                            drawOnChartArea: false, // only want the grid lines for one axis to show up
                        },
                        ticks: {
                            min: 0,
                            max: 100,
                            callback: function(value) {
                                return value + "%";
                            }
                        },
                        scaleLabel: {
                            display: true,
                            labelString: "Percent"
                        }
                    },
                    x: {
                        type: 'time',
                        time: {
                            tooltipFormat: "hh:mm:ss",
                            displayFormats: {
                                hour: 'hh:mm:ss'
                            }
                        },
                        ticks: {
                            autoSkip: true,
                            maxTicksLimit: 5,
                            maxRotation: 0,
                            minRotation: 0
                        } 
                    }
                },
                plugins: {
                    autocolors: false,
                    annotation: {
                        annotations: {
                        }
                    },
                    legend: {
                        position: 'bottom',
                        labels: {
                            usePointStyle: true
                        }
                    }
                }
                
            }
        });

        this.updateDomain();
    }

    updateChart(chartId) {
        console.log('Updating chart…');
        let t = this;
        
        // Query the server for state logs that are after the last state
        // query that we made
        fetch('/state_logs?since=' + this.last_state_update.toString(), {
           method: 'GET', 
           headers: {
               'Accept': 'application/json',
           }
        })
        .then((response) => response.json())
        .then((data) => { t.processStateData(data); })
        .catch((error) => {
           console.error('Communication Error Fetching State:', error);
        });

        // Query the server for activity logs that end after the last 
        // update that we received.
        fetch('/activity_logs?since=' + this.last_activity_update.toString(), {
           method: 'GET', 
           headers: {
               'Accept': 'application/json',
           }
        })
        .then((response) => response.json())
        .then((data) => { t.processActivity(data); })
        .catch((error) => {
           console.error('Communication Error Fetching Activity:', error);
        });
    }

    processStateData(data) {
        // Store the current server time (in the server timescale)
        // so that we don't refetch activity
        this.last_state_update = data['time'];
        
        // Calculate when the chart should end (in the local timescale)
        const domainEnd = this.last_state_update*1000
        
        if (this.server_time_offset === null) {
            this.server_time_offset = domainEnd - Date.now();
            console.log(this.server_time_offset);
        }
        // Append the new data to the chart
        this.appendStateData(data);
        
        this.updateDomain(domainEnd, this.chartDuration);
    
        // Update the chart to show the new data
        this.chart.update()
    }
    
    appendStateData(data) {
        // The data arrives with the most recent log first. Reverse it to append to the end.
        let states = data.state.reverse();
        // Map the times from the server time to the local time
        // and map percentages from 0 - 1 to 0 - 100
        states.forEach((state, index) => {
            state.time = state.time*1000 - this.server_time_offset;
            state.duty *= 100;
        });
        
        if (this.stateData.length) {
            // There is a chance that the query returns some values that we
            // already have. Remove any new elements that are older than the 
            // end of the existing data
            while (states.length && this.stateData[this.stateData.length - 1].time >= states[0].time) {
                states.shift();
            }
        }
        
        // Append the new data to the datasets
        this.stateData.push(...states);
    }

    processActivity(data) {
        // Store the current server time (in the server timescale)
        // so that we don't refetch events that have been received
        // in their entirety. Note that activity events are fetched
        // based on their end time, which may be in the future, so
        // the same event may be received multiple times while it is
        // running.
        this.last_activity_update = data['time'];
                
        // Append the new data to the chart
        this.appendActivityData(data);
    
        // Update the chart to show the new data
        this.chart.update()
    }

    appendActivityData(data) {
        // Create annotations for activities
        data.activity.forEach((activity, index) => {
            const start = activity.start*1000 - this.server_time_offset;
            const end = activity.stop*1000 - this.server_time_offset;

            // Choose the colour based on the event type
            let colour;
            let type;
            if (activity.event == "R") { // Compressor motor is running
                colour = '66, 245, 209';
            } else if (activity.event == "P") {	// Compressor purge valve is open
                colour = '245, 212, 66';
            } else {
                colour = '230, 230, 230';
            }
            
            // Update the activity details in the annotations table. Note that if an
            // activity is still 'running' (it ends in the future) it may be received
            // multiple times.
            this.chart.options.plugins.annotation.annotations['activity_id_' + activity.start.toString()] = {
                type: 'box',
                display: this.activitiesVisible,
                xMin: start,
                xMax: end,
                yScaleID: 'percent',
                backgroundColor: 'rgba(' + colour + ', 0.25)',
                borderColor: 'rgba(' + colour + ', 0.6)'
            }
        });
        
        // Create annotations for commands
        data.commands.forEach((activity, index) => {
            const time = activity.time*1000 - this.server_time_offset;

            // Choose the colour based on the event type
            let colour;
            let labelText;
            let width = 1;
            if (activity.command == "O") { // Compressor on
                colour = 'rgba(0, 255, 0, 1)';
                labelText = 'On';
                width = 4;
            } else if (activity.command == "F") { // Compressor off
                colour = 'rgba(255, 0, 0, 1)';
                labelText = 'Off';
                width = 4;
            } else if (activity.command == "R") { // Compressor motor run request
                colour = 'rgba(0, 255, 0, 0.5)';
                labelText = 'Run';
            } else if (activity.command == "|") { // Compressor pause request
                colour = 'rgba(255, 0, 0, 0.5)';
                labelText = 'Pause';
            } else {
                // Either purge, or an unknown command. Do not display.
                return;
            }
            
            // Update the command details in the annotations table.
            this.chart.options.plugins.annotation.annotations['command_id_' + activity.time.toString()] = {
                type: 'line',
                display: this.commandsVisible,                
                xMin: time,
                xMax: time,
                yScaleID: 'percent',
                borderColor: colour,
                borderWidth: width,
                label: {
                    content: labelText,
                    position: 'end',
                    rotation: 90,
                    borderWidth: 2,
                    color: colour,
                    borderColor: colour,
                    backgroundColor: 'rgba(255, 255, 255, 255)',
                    display: true
                }
            }
        });
    }

    updateDomain(domainEnd = null) {
        if (domainEnd === null) {
            let now = Date.now();
            this.chart.options.scales.x.max = now;
            this.chart.options.scales.x.min = now - this.chartDuration;
        } else {
            // Calculate when the chart should start
            const domainStart = domainEnd - this.chartDuration;

            // Update the domain of the x axis
            this.chart.options.scales.x.min = domainStart - this.server_time_offset;
            this.chart.options.scales.x.max = domainEnd - this.server_time_offset;
        }
    }
}