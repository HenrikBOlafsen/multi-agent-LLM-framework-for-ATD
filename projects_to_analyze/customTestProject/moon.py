from car import getMassOfAverageCar

class Moon:
    def __init__(self, mass):
        self.mass = mass

    def getMassAsAmountOfCars(self):
        return self.mass / getMassOfAverageCar()

def getCurentDistanceToTheMoon():
    # this probably varies depending on where in the orbit it is. But let us ignore that for simpicity sake
    return 384400

def getMassOfTheMoon():
    # this probably varies depending on where in the orbit it is. But let us ignore that for simpicity sake
    return 73000000000000000000000