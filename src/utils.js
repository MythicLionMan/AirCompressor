function submitSettings(formID, success = null, failure = null) {
    // Convert the form to json
    const formData = new FormData(document.querySelector("form"))
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