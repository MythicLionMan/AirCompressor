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
        type: 'bar',
        data: {
            labels: ['Red', 'Blue', 'Yellow', 'Green', 'Purple', 'Orange'],
            datasets: [{
                label: '# of Votes',
                data: [12, 19, 3, 5, 2, 3],
                backgroundColor: [
                    'rgba(255, 99, 132, 0.2)',
                    'rgba(54, 162, 235, 0.2)',
                    'rgba(255, 206, 86, 0.2)',
                    'rgba(75, 192, 192, 0.2)',
                    'rgba(153, 102, 255, 0.2)',
                    'rgba(255, 159, 64, 0.2)'
                ],
                borderColor: [
                    'rgba(255, 99, 132, 1)',
                    'rgba(54, 162, 235, 1)',
                    'rgba(255, 206, 86, 1)',
                    'rgba(75, 192, 192, 1)',
                    'rgba(153, 102, 255, 1)',
                    'rgba(255, 159, 64, 1)'
                ],
                borderWidth: 1
            }]
        },
        options: {
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });
}

function updateChart(chartId) {
    console.log('Updating chart…');
}
