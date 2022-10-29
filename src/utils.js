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