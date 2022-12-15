# NOTE This will divide by 0 if mean(timeX) == 0
# Linear least squares requires solving for m and b by minimizing the square of the sum of the residual function for all of the points.
# The residual for a single point n is rn = yn - (mxn + b).
#    r^2 = (y - (b + xm))^2
#    r^2 = y^2 - 2y(b + xm) + (b + xm)(b + xm)
#    r^2 = y^2 - 2yb - 2yxm + b^2 + 2bxm + x^2m^2
#    r^2 = y^2 + b^2 - 2yb + 2bxm - 2yxm + x^2m^2
#
#    Calculating the partial derivative with respect to b, we get the following for each point:
#    r^2 = y^2 + b^2  + b (-2y + 2xm) - 2yxm + x^2m^2
#    r^2 = b^2 + b(-2y + 2xm) + y^2 - 2yxm + x^2m^2
#    db = 2b + (-2y + 2xm)
#    db = 2xm + 2b - 2y
#
#    Calculating the partial derivative with respect to m, we get the following for each point:
#    r^2 = y^2 + b^2 - b2y + m(2bx - 2yx) + x^2m^2
#    r^2 = m^2x^2 + m(2bx - 2yx) + b^2 - 2by
#    dm = 2mx^2 + (2bx - 2yx)
#    dm = 2mx^2 + 2bx - 2yx
#
# If each point is substituded into the partial derivative functions and summed, we get the coefficients for two normal
# equations. Solving these two equations yields the linear equation of the line of best fit.
#
# The resulting equations are:
# 1) 0 = mA + bB + C
# 2) 0 = mD + bE + F
# Rewrite equation 2 in terms of b
# b = (-mD - F)/E
# Substitute equation 2 into equation 1
# 0 = mA + B(-mD - F)/E + C
# 0 = mA - mDB/E -BF/E + C
# 0 = m(A - DB/E) -BF/E + C
# m = (BF/E - C)/(A - DB/E)
#
# Rewrite equation 1 in terms of m
# m = (-bB - C)/A
# Substitute equation 1 into equation 2
# 0 = mD + bE + F
# 0 = D(-bB - C)/A + bE + F
# 0 = -bDB/A - DC/A + bE + F
# 0 = b(E - DB/A) - DC/A + F
# b = (DC/A - F)/(E - DB/A)
# b = (equation[1][0]*equation[0][2]/equation[0][0] - equation[1][2])/(equation[1][1] - equation[1][0]*equation[0][1]/equation[0][0])
def linear_least_squares(data, time_scale = 1):
    # Time will be squared, so large values can blow up quickly. To prevent this normalize time by subtracting the min
    # from all values
    min_time = min(data, key=lambda x:x[0])[0]

    equations = [[0, 0, 0], [0, 0, 0]]
    for i in data:
        timeX = (i[0] - min_time)*time_scale
        valueY = i[1]
        
        equations[0][0] = equations[0][0] + 2*timeX
        equations[0][1] = equations[0][1] + 2
        equations[0][2] = equations[0][2] - 2*valueY
        
        equations[1][0] = equations[1][0] + 2*timeX*timeX
        equations[1][1] = equations[1][1] + 2*timeX
        equations[1][2] = equations[1][2] - 2*timeX*valueY
        
    # Find the equation of the line that minimizes the residuals
    
    # Substitute the second equation into the first to get m
    m = ((equations[0][1]*equations[1][2]/equations[1][1] - equations[0][2]))/(equations[0][0] - equations[1][0]*equations[0][1]/equations[1][1])
    # Substitute the first equation into the second to get b
    b = (equations[1][0]*equations[0][2]/equations[0][0] - equations[1][2])/(equations[1][1] - equations[1][0]*equations[0][1]/equations[0][0])

    # TODO Only for testing.
    #print("m = " + str(m))
    #print("b = " + str(b))
    #print("residuals = " + str(residuals(m, b, data)))
    #print("residuals_total = " + str(residuals_total(m, b, data)))

    return (m, b)

def residuals(m, b, data):
    return [p[1] - (m*p[0] + b) for p in data]

def residuals_total(m, b, data):
    return sum([r*r for r in residuals(m, b, data)])

# Test data (from: https://en.wikipedia.org/wiki/Linear_least_squares#Example )
#
#     (1,6), (2, 5), (3,7), (4, 10)
#
#
#    (1, 6)
#    db = 2m + 2b - 12
#    dm = 2m + 2b - 12
#    (2, 5)
#    db = 4m + 2b - 10
#    dm = 8m + 4b - 20
#    (3, 7)
#    db = 6m + 2b - 14
#    dm = 18m + 6b - 42
#    (4, 10)
#    db = 8m + 2b - 20
#    dm = 32m + 8b - 80
#
#    Sum =
#    db = 20m + 8b - 56
#    dm = 60m + 20b - 154
def test_wiki():
    test([[1, 6], [2, 5], [3, 7], [4, 10]])

def test_sample():
    test([[1671024242, 90.0], [1671024240, 90.1], [1671024238, 90.2]])

def test(d):
    (m, b) = linear_least_squares(d)
    print("m = " + str(m))
    print("b = " + str(b))
    print("residuals = " + str(residuals(m, b, d)))
    print("residuals_total = " + str(residuals_total(m, b, d)))
