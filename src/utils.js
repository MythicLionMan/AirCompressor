function submitSettings(formID, success = null, failure = null) {
    // Convert the form to json
    const formData = new FormData(document.getElementById(formID))
    var data = {};
    formData.forEach((value, key) => data[key] = value);
    
    let failureWrapper = function() {
        if (failure) {
            failure();
        } else {
            alert('Error updating settings');
        }
    }

    let successWrapper = function() {
       console.log('Settings updated succesfully');
    
        if (success) {
            success();
        } else {
            alert('Settings Updated');
        }
    }

    // Submit to the server
    fetch('/settings', {
       method: 'POST', 
       headers: {
           'Accept': 'application/json',
           'Content-Type': 'application/json'
       },
       body: JSON.stringify(data)
    })
    .then((response) => response.json())
    .then((data) => {
       if (data['result'] == 'ok') {
           successWrapper();
       } else {
           console.log('Error updating remote')       
           failureWrapper();
       }
    })
    .catch((error) => {
       console.error('Communication Error:', error);
       failureWrapper();
    });
}

var stateMonitorId = null;
function monitorState(interval = 5000) {
    if (interval == 0) {
        if (stateMonitorId) {
            clearInterval(stateMonitorId);
            stateMonitorId = null;
        }
    } else {
        stateMonitorId = setInterval(fetchState, interval);
    }
}

function fetchState() {
    // Query the server
    fetch('/status', {
       method: 'GET', 
       headers: {
           'Accept': 'application/json',
       }
    })
    .then((response) => response.json())
    .then((data) => {
        // Copy the state data to the html elements whose id matches
        // the keys fetched in the state dictionary
        for (const [key, value] of Object.entries(data)) {        
            element = document.getElementById(key);
            if (element) element.innerHTML = value;
        };
    })
    .catch((error) => {
       console.error('Communication Error:', error);
    });
}

chartMonitorId = null;
chart = null;
function monitorChart(chartId, interval = 5000) {
    if (interval == 0) {
        if (chartMonitorId) {
            clearInterval(chartMonitorId);
            chartMonitorId = null;
        }
    } else {
        if (!chart) {
            if (document.readyState === 'complete') {
                chart = configureChart(document.getElementById(chartId).getContext('2d'));
            } else {
                console.log('Document is not ready, scheduling chart setup when page is loaded.');
                window.onload = function() {
                    chart = configureChart(document.getElementById(chartId).getContext('2d'));
                }
            }
        }
        chartMonitorId = setInterval(function(){ updateChart() }, interval);
    }
}

let width, height, gradient;
function getGradient(ctx, chartArea) {
    const chartWidth = chartArea.right - chartArea.left;
    const chartHeight = chartArea.bottom - chartArea.top;
    if (!gradient || width !== chartWidth || height !== chartHeight) {
        // Create the gradient because this is either the first render
        // or the size of the chart has changed
        width = chartWidth;
        height = chartHeight;
        gradient = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top);
        gradient.addColorStop(0, 'rgb(75, 192, 192)');
        gradient.addColorStop(1, 'rgb(255, 99, 132)');
    }

    return gradient;
}

function configureChart(ctx) {
    console.log('Document is ready, setting up chart');
    return new Chart(ctx, {
        type: 'scatter',
        data: {
            datasets: [{
                label: 'Tank Pressure',
                showLine: true,
                data: [],
                yAxisID: 'pressure',
                borderColor: '#FF0000'
            },{
                label: 'Line Pressure',
                showLine: true,
                data: [],
                yAxisID: 'pressure',
                borderColor: '#FFFF00'
            },{
                label: 'Duty',
                showLine: true,
                data: [],
                yAxisID: 'percent',
                borderColor: function(context) {
                    const chart = context.chart;
                    const {ctx, chartArea} = chart;

                    if (!chartArea) {
                      // This case happens on initial chart load
                      return;
                    }
                    return getGradient(ctx, chartArea);
                },
            }]
        },
        options: {
            elements: {
                point: {
                    radius: 0
                }
            },
            scales: {
                pressure: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    min: 0,
                    max: 150
                },
                percent: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    min: 0,
                    max: 1,

                    // grid line settings
                    grid: {
                        drawOnChartArea: false, // only want the grid lines for one axis to show up
                    },
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
                }
            }
            
        }
    });    
}

last_state_update = 0;
last_activity_update = 0;
server_time_offset = null;
function updateChart(chartId) {
    console.log('Updating chart…');

    // Query the server for state logs
    fetch('/state_logs?since=' + last_state_update.toString(), {
       method: 'GET', 
       headers: {
           'Accept': 'application/json',
       }
    })
    .then((response) => response.json())
    .then((data) => {
        // Store the current server time (in the server timescale)
        last_state_update = data['time'];
        
        // Calculate when the chart should end (in the local timescale)
        domainEnd = last_state_update*1000
        
        if (server_time_offset === null) {
            server_time_offset = domainEnd - Date.now();
            console.log(server_time_offset);
        }
        // Append the new data to the chart
        chartAppendState(chart, data, server_time_offset);
        // TODO This duration could be a configuration parameter. It is local,
        //      since we can make the chart as long as we'd like (by keeping the data around)
        chartUpdateDomain(chart, domainEnd, 5*60*1000);
    
        // Update the chart to show the new data
        chart.update()
    })
    .catch((error) => {
       console.error('Communication Error Fetching State:', error);
    });

    // Query the server for activity logs
    fetch('/activity_logs?since=' + last_activity_update.toString(), {
       method: 'GET', 
       headers: {
           'Accept': 'application/json',
       }
    })
    .then((response) => response.json())
    .then((data) => {
        // Store the current server time (in the server timescale)
        // TODO If the query is limited then events that have been received in the
        //      past but have been updated are not returned. This leaves every activity
        //      unterminated. Activities that have been modified need to be refetched.
        //      This is because activities can be modified, unlike other logs. One solution
        //      would be to fetch based on modified time, rather than activity time. Another
        //      would be to fetch based on stop time rather than modified time.
        //      Always fetching all activities is somewhat expensive, since every query
        //      will return the full buffer.
        last_activity_update = 0;//data['time'];
                
        // Append the new data to the chart
        chartAppendActivity(chart, data, server_time_offset);
    
        // Update the chart to show the new data
        chart.update()
    })
    .catch((error) => {
       console.error('Communication Error Fetching Activity:', error);
    });
}

function chartAppendState(chart, data, server_time_offset) {
    // The data arrives with the most recent log first. Reverse it to append to the end.
    states = data.state.reverse();
    // Map the times from the server time to the local time
    states.forEach((state, index) => {
        state.time = state.time*1000 - server_time_offset;
    });
    // Convert to x/y values for different datasets
    tankPressures = states.map((state) => { return { x: state.time, y: state.tank_pressure}});
    linePressures = states.map((state) => { return { x: state.time, y: state.line_pressure}});
    dutyData = states.map((state) => { return { x: state.time, y: state.duty}});
    
    // Append the new data to the datasets
    chart.data.datasets[0].data.push(...tankPressures);
    chart.data.datasets[1].data.push(...linePressures);
    chart.data.datasets[2].data.push(...dutyData);
}

function chartAppendActivity(chart, data, server_time_offset) {
    activities = data.activity;

    // Map the times from the server time to the local time
    activities.forEach((activity, index) => {
        start = activity.start*1000 - server_time_offset;
        end = activity.stop*1000 - server_time_offset;

        // Choose the colour based on the event type
        if (activity.event == "R") { // Compressor motor is running
            colour = 'rgba(66, 245, 209, 0.25)';
        } else if (activity.event == "P") {	// Compressor purge valve is open
            colour = 'rgba(245, 212, 66, 0.25)';
        } else {
            colour = 'rgba(230, 230, 230, 0.25)';
        }
        
        // Update the activity details in the annotations table
        chart.options.plugins.annotation.annotations['activity_id_' + activity.start.toString()] = {
            type: 'box',
            xMin: start,
            xMax: end,
            yScaleID: 'percent',
            backgroundColor: colour            
        }
    });
}

function chartUpdateDomain(chart, domainEnd, duration) {
    // Calculate when the chart should start
    domainStart = domainEnd - duration;

    // Update the domain of the x axis
    chart.options.scales.x.min = domainStart - server_time_offset;
    chart.options.scales.x.max = domainEnd - server_time_offset;
}
