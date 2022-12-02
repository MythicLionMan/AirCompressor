
class PieChart {
    constructor(gauge, title) {
        this.gauge = gauge;
        this.title = title;
        
        this.sweep = 1.5 * Math.PI;
        this.startAngle = 0.75 * Math.PI;
        this.borderWidth = 5;
        this.centreRadius = 0.7;
        
        this.value = 0.6;
        this.maxValue = 0.6;
                
        this.valueFont = "20px serif";
        this.valueLabelColour = '#536878';
        this.titleFont = "13px serif";
        
        this.backgroundColour = '#DDD';
        this.sweepColour = '#CCC';
        this.alertRangeColour = '#AAA';
        this.valueRangeColourStart = '#00FF00';
        this.valueRangeColourEnd = '#F00';
        this.valueRangeColours = ['#209c05', '#85e62c', '#ebff0a', '#f2ce02', '#ff0a0a']
    }
    
    valueToAngle(value) {
        return this.sweep*value + this.startAngle;
    }
        
    draw() {
        var ctx = this.gauge.getContext("2d");
        var width = this.gauge.width;
        var height = this.gauge.height;
        var squareSize = Math.min(width, height);
        var outerRadius = squareSize/2 - 5;
        var innerRadius = outerRadius - this.borderWidth;
        var centreRadius = innerRadius * this.centreRadius;
        var titleYOffset = innerRadius - 4;
        
        ctx.save();
        ctx.clearRect(0, 0, width, height);
        // Transform to the centre
        ctx.setTransform(1, 0, 0, 1, squareSize/2, squareSize/2);
        
        // Background
        ctx.fillStyle = this.backgroundColour;
        ctx.beginPath();
        ctx.arc(0, 0, outerRadius, 0, 2 * Math.PI);
        ctx.fill();
        
        // Sweep Range
        ctx.fillStyle = this.sweepColour;
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.arc(0, 0, innerRadius, this.valueToAngle(0), this.valueToAngle(1));
        ctx.closePath();
        ctx.fill();

        // Alert Range
        ctx.fillStyle = this.alertRangeColour;
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.arc(0, 0, innerRadius, this.valueToAngle(0), this.valueToAngle(this.maxValue));
        ctx.closePath();
        ctx.fill();
        
        // Value Range
        const gradient = ctx.createConicGradient(this.valueToAngle(0) + Math.PI/2, 0, 0);
        ctx.fillStyle = gradient;
        const indexScale = this.maxValue/(this.valueRangeColours.length - 1)*this.sweep/(Math.PI*2);
        this.valueRangeColours.forEach(function (colour, i) {
            gradient.addColorStop(i*indexScale, colour);
        });
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.arc(0, 0, innerRadius, this.valueToAngle(0), this.valueToAngle(this.value));
        ctx.closePath();
        ctx.fill();
        
        // Centre fill
        ctx.fillStyle = this.backgroundColour;
        ctx.beginPath();
        ctx.arc(0, 0, centreRadius, 0, 2 * Math.PI);
        ctx.fill();

        // Value text
        ctx.font = this.valueFont;
        ctx.fillStyle = this.valueLabelColour;
        ctx.textBaseline = 'middle';
        ctx.textAlign = 'center';
        ctx.fillText(Math.round(this.value * 100) + "%", 0, 0);

        // Gauge label
        if (this.title) {
            ctx.font = this.titleFont;
            ctx.textBaseline = 'bottom';
            ctx.textAlign = 'center';
            ctx.fillText(this.title, 0, titleYOffset);
        }
        
        ctx.restore();
    }
}

