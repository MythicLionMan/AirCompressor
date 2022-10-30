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

function configureChart(ctx) {
    console.log('Document is ready, setting up chart');
    return new Chart(ctx, {
        type: 'scatter',
        data: {
            datasets: [{
                label: 'Tank Pressure',
                showLine: true,
                data: []
            },{
                label: 'Duty',
                showLine: true,
                data: []
            }]
        }
        //options: {
        //    scales: {
        //        x: {
        //            min: -9000,
        //            max: 120000
        //        },
                //x: {
                //    type: 'time',
                //    time: {
                //        tooltipFormat: "hh:mm:ss",
                //        displayFormats: {
                //            hour: 'hh:mm:ss'
                //        }
                //    },
                //},
       //         y: {
       //             beginAtZero: true
       //         }
       //     }
       // }
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
        // Calculate when the chart should start
        // TODO This duration could be a configuration parameter. It is local,
        //      since we can make the chart as long as we'd like (by keeping the data around)
        domainStart = domainEnd - 5*60*1000;
        
        if (server_time_offset === null) {
            server_time_offset = domainEnd - Date.now();
            console.log(server_time_offset);
        }
        chartAppendState(chart, data, server_time_offset);
        
        // Update the chart to show the new data
        chart.update()
    })
    .catch((error) => {
       console.error('Communication Error:', error);
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
    pressures = states.map((state) => { return { x: state.time, y: state.tank_pressure}});
    dutyData = states.map((state) => { return { x: state.time, y: state.duty}});
    
    // Append the new data to the datasets
    chart.data.datasets[0].data.push(...pressures);
    chart.data.datasets[1].data.push(...dutyData);
    
    //times = chart.data.datasets[0].data.map((point) => { return point.x; });
    //chart.options.scales.x.min = Math.min(...times)
    //chart.options.scales.x.max = Math.max(...times)
}
