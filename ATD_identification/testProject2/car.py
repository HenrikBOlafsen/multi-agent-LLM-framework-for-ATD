from calculateDistance import getTotalTravelDistance

class Car:
    def __init__(self, car_name="", weight=1500):
        self.car_name = car_name
        self.weight = weight
        self.trips = []

    def get_car_name(self):
        return self.car_name
    
    def get_weight(self):
        return self.weight
    
    def register_trip(self, km_driven):
        self.trips.append(km_driven)

    def get_total_distance_driven():
        return getTotalTravelDistance()
    
def getMassOfAverageCar():
    return 1500