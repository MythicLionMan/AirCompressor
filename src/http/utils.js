settings = {
    debug: window.location.href.startsWith('file://'),
    stateQueryInterval: 1000,
    chartQueryInterval: 5000,
    stateFetchLateInterval: 500,        // If a query takes longer than this to return, a warning is posted
    fetchRecoveryInterval: 10000,       // When a fetch is issued, sending another query is blocked until it returns or this time has elapsed
    chartDomainUpdateInterval: 1000, 
    chartDuration: [ 5*60*1000, 10*60*1000, 20*60*1000 ]
};

function assignKeyPath(destination, path, value) {
    if (!Array.isArray(path)) path = path.split('.');
    
    key = path.shift();
    if (path.length == 0) {
        destination[key] = value;
    } else {
        if (!(key in destination)) destination[key] = {};
        assignKeyPath(destination[key], path, value);
    }
}

// This lock can be used to block sending a new fetch request while one is still outsanding.
// After recovery time has elapsed the lock will open up regardless, so that a new
// request can be made.
class FetchLock {
    constructor(recovery) {
        this.recovery = recovery;
    }
    
    // Returns false if a new fetch can be scheduled, true if there is an outstanding
    // fetch that hasn't timed out yet. If this is unlocked it will be locked after the
    // call.
    isLocked() {
        if (this.fetchPending) {
            // The last fetch is still pending, so don't start a new one
            return true;
        }
        let t = this;
        this.fetchPending = setTimeout(() => t.unlock(), this.recovery);
        return false;
    }
    
    // Clears the pending lock and allows another fetch to proceed. Call this when
    // a fetch returns to unlock immediately. If it isn't called explicitly it will
    // eventually time out and the block will reset.
    unlock() {
        if (this.fetchPending) {
            clearTimeout(this.fetchPending);
            this.fetchPending = null;
        }
    }
}
