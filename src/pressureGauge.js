class Gauge {
    constructor(gauge) {
        this.gauge = gauge;
        
        this.min = 0;
        this.max = 150;
        this.sweep = 1.5*Math.PI;
        this.startAngle = 0.75 * Math.PI;
        
        this.value = 0;
        this.startPressure = 0;
        this.stopPressure = 0;
        this.alarmPressure = 0;
        
        this.ringWidth = 4;
        this.majorTickWidth = 2;
        this.minorTickWidth = 1;
        this.majorTickLength = 14;
        this.minorTickLength = 7;
        this.minorTickStride = 2;
        this.majorTickStride = 10;
        
        this.labelFont = "15px serif";
        this.valueFont = "25px serif";
        this.labelColour = '#536878';
        this.valueYOffset = 5;
        this.tickLabelInset = 15;
        
        this.setPointLength = 22;
        this.setPointWidth = 8;
        this.alarmWidth = 6;
        this.valueBaseWidth = 5;
        this.valueTipWidth = 2;
        this.valueRingClearance = 3;
    }
    
    valueToAngle(value) {
        var percentage = value/(this.max - this.min);
        return this.sweep*percentage + this.startAngle;
    }
        
    draw() {
        var ctx = this.gauge.getContext("2d");
        var width = this.gauge.width;
        var height = this.gauge.height;
        var squareSize = Math.min(width, height);
        var outerRadius = squareSize/2 - 5;
        var innerRadius = outerRadius - this.ringWidth/2;
        
        ctx.save();
        ctx.clearRect(0, 0, width, height);
        // Transform to the centre
        ctx.setTransform(1, 0, 0, 1, squareSize/2, squareSize/2);
        
        // Outer ring
        ctx.strokeStyle = 'black';
        ctx.lineWidth = this.ringWidth;
        ctx.beginPath();
        ctx.arc(0, 0, outerRadius, 0, 2 * Math.PI);
        ctx.stroke();

        ctx.strokeStyle = this.labelColour;
        ctx.fillStyle = this.labelColour;

        // Minor ticks
        ctx.lineWidth = this.minorTickWidth;
        this.ticks(ctx, this.minorTickStride, innerRadius - this.minorTickLength, innerRadius);

        // Major ticks
        ctx.lineWidth = this.majorTickWidth;
        this.ticks(ctx, this.majorTickStride, innerRadius - this.majorTickLength, innerRadius);
        
        // Tick labels
        ctx.font = this.labelFont;
        this.tickLabels(ctx, this.majorTickStride, innerRadius - this.majorTickLength - this.tickLabelInset);
        
        // Value text
        ctx.font = this.valueFont;
        ctx.textBaseline = 'top';
        ctx.textAlign = 'center';
        ctx.fillText(Math.round(this.value) + " PSI", 0, this.valueYOffset);
        
        // Current Value Pointer
        if (this.value) {
            ctx.fillStyle = 'black';
            this.pointer(ctx, this.value, this.valueBaseWidth, this.valueTipWidth, innerRadius - this.valueRingClearance);
            
            var setPointStart = outerRadius - this.setPointLength;
            var setPointEnd = outerRadius;
        }

        // Alarm Pressure
        ctx.lineCap = 'round';
        if (this.alarmPressure) {
            ctx.strokeStyle = 'orange';
            ctx.lineWidth = this.alarmWidth;
            ctx.beginPath();
            this.tick(ctx, this.alarmPressure, setPointStart, setPointEnd);
            ctx.stroke();
        }
        
        // On pressure
        ctx.lineWidth = this.setPointWidth;
        if (this.startPressure) {
            ctx.strokeStyle = 'green';
            ctx.beginPath();
            this.tick(ctx, this.startPressure, setPointStart, setPointEnd);
            ctx.stroke();
        }
        
        // Off Pressure
        if (this.stopPressure) {
            ctx.strokeStyle = 'red';
            ctx.beginPath();
            this.tick(ctx, this.stopPressure, setPointStart, setPointEnd);
            ctx.stroke();
        }
        
        ctx.restore();
    }

    pointer(ctx, value, baseWidth, tipWidth, length) {
        // indicator

        ctx.save();
        // Rotate the coordinate system by the value angle
        var angle = this.valueToAngle(this.value);
        ctx.transform(Math.sin(angle), -Math.cos(angle), Math.cos(angle), Math.sin(angle), 0, 0);
        
        // Arm
        ctx.beginPath();
        ctx.moveTo(-baseWidth/2, 0);
        ctx.lineTo(baseWidth/2, 0);
        ctx.lineTo(tipWidth/2, length);
        ctx.lineTo(-tipWidth/2, length);
        ctx.closePath();
        ctx.fill();

        // Center circle
        ctx.beginPath();
        ctx.arc(0, 0, 5, 0, 2 * Math.PI);
        ctx.fill();
        ctx.restore();
    }
    
    tick(ctx, value, startLength, endLength) {
        var angle = this.valueToAngle(value);
        ctx.moveTo(Math.cos(angle)*startLength, Math.sin(angle)*startLength);
        ctx.lineTo(Math.cos(angle)*endLength, Math.sin(angle)*endLength);
    }

    ticks(ctx, stride, startLength, endLength) {
        ctx.beginPath();
        for (var i = this.min;i <= this.max;i += stride) {
            this.tick(ctx, i, startLength, endLength);
        }
        ctx.stroke();
    }

    tickLabels(ctx, stride, endLength) {
        ctx.textBaseline = 'middle';
        ctx.textAlign = 'center';
        for (var i = this.min;i <= this.max;i += stride) {
            var angle = this.valueToAngle(i);
            var textDim = ctx.measureText(i);
            ctx.fillText(i, Math.cos(angle)*endLength, Math.sin(angle)*endLength);
        }
    }
}

