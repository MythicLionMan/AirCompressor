class ChartMonitor {
    constructor(chartId) {
        this.monitorId = null;
        this.chart = null;

        this.last_state_update = 0;
        this.last_activity_update = 0;
        this.server_time_offset = null;

        this.activitiesVisible = true;
        this.commandsVisible = true;

        this.stateFetchPending = new FetchLock(settings.fetchRecoveryInterval);
        this.activityFetchPending = new FetchLock(settings.fetchRecoveryInterval);
        
        this.setChartDurationIndex(0);

        // Create the chart
        this.configureChart(document.getElementById(chartId).getContext('2d'));
    }

    monitor(queryInterval = null, domainUpdateInterval = null) {
        queryInterval ??= settings.chartQueryInterval;
    
        if (queryInterval == 0) {
            if (this.monitorId) {
                clearInterval(this.monitorId);
                this.monitorId = null;
            }
        } else if (settings.debug) {
            let t = this;
            this.monitorId = setInterval(() => t.appendDemoData(), queryInterval);
            this.appendDemoData();
        } else {
            let t = this;
            this.monitorId = setInterval(() => t.fetchChartData(), queryInterval);
            this.fetchChartData();
        }

        domainUpdateInterval ??= settings.chartDomainUpdateInterval;

        if (domainUpdateInterval == 0) {
            if (this.chartDomainId) {
                clearInterval(this.chartDomainId);
                this.chartDomainId = null;
            }
        } else {
            let t = this;
            this.chartDomainId = setInterval(() => {
                t.updateDomain();
                t.chart.update();
            }, domainUpdateInterval);
            this.updateDomain();
            this.chart.update();
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
                animation: {
                    duration: settings.chartDomainUpdateInterval,
                    easing: 'linear'
                },
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
    }

    appendDemoData(demoDuration = 5, demoDatapoints = 5) {
        const now = Date.now() / 1000;
        
        // Generate some fake states
        let states = Array(demoDatapoints);
        for (let i = 0; i < states.length; i++) {
            states[i] = {
                time: now - demoDuration * i / demoDatapoints,
                tank_pressure: 110 + Math.random() * 20,
                line_pressure: 80 + Math.random() * 20,
                duty: Math.random()
            };
        }
        
        this.processStateData({
            time: now,
            state: states
        });
    }
    
    fetchChartData() {
        console.log('Updating chart…');
        let t = this;
        
        if (!this.stateFetchPending.isLocked()) {
            // Query the server for state logs that are after the last state
            // query that we made
            fetch('/state_logs?since=' + this.last_state_update.toString(), {
               method: 'GET',
               headers: {
                   'Accept': 'application/json',
               }
            })
            .then((response) => response.json())
            .then((data) => t.processStateData(data))
            .catch((error) => console.error('Communication Error Fetching State:', error))
            .finally(() => t.stateFetchPending.unlock());
        }
        
        // Query the server for activity logs that end after the last
        // update that we received.
        if (!this.activityFetchPending.isLocked()) {
            fetch('/activity_logs?since=' + this.last_activity_update.toString(), {
               method: 'GET',
               headers: {
                   'Accept': 'application/json',
               }
            })
            .then((response) => response.json())
            .then((data) => t.processActivity(data))
            .catch((error) => console.error('Communication Error Fetching Activity:', error))
            .finally(() => t.activityFetchPending.unlock());
        }
    }

    processStateData(data) {
        // Store the current server time (in the server timescale)
        // so that we don't refetch activity
        this.last_state_update = data['time'];
        
        // Calculate when the chart should end (in the local timescale)
        const domainEnd = this.last_state_update*1000
        
        if (this.server_time_offset === null) {
            this.server_time_offset = domainEnd - Date.now();
            console.log('ChartMonitor.server_time_offset = ' + this.server_time_offset.toString());
        }
        // Append the new data to the chart
        this.appendStateData(data);
        
        // If the chart domain is not being updated automatically, update it with the
        // chart data
        if (this.chartDomainId == null) {
            this.updateDomain(domainEnd, this.chartDuration);
        }
        
        // Update the chart to show the new data
        this.chart.update('none')
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
            // Have the chart end in the past, so the gap where new data appears
            // isn't visible.
            let domainEnd = Date.now() - settings.chartQueryInterval;
            this.chart.options.scales.x.max = domainEnd;
            this.chart.options.scales.x.min = domainEnd - this.chartDuration;
        } else {
            // Calculate when the chart should start
            const domainStart = domainEnd - this.chartDuration;

            // Update the domain of the x axis
            this.chart.options.scales.x.min = domainStart - this.server_time_offset;
            this.chart.options.scales.x.max = domainEnd - this.server_time_offset;
        }
    }
}

