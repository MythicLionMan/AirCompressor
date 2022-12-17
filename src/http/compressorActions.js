class CompressorActions {
    constructor(stateMonitor = null) {
        this.stateMonitor = stateMonitor;
    }
        
    submitSettings(formID) {
        // Convert the form to json
        const formData = new FormData(document.getElementById(formID))
        let data = {};
        formData.forEach((value, key) => assignKeyPath(data, key, value));
                
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
        if (this.stateMonitor) {
            this.stateMonitor.fetchState();
        }
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
