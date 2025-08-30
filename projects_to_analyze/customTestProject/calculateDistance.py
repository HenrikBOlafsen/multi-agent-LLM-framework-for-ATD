import moon

def getTotalTravelDistance(trip_lengths):
    total_travel_distance = sum(trip_lengths)
    return total_travel_distance, distanceToPercentageOfDistanceToMoon(total_travel_distance)

def distanceToPercentageOfDistanceToMoon(distance):
    return distance / moon.getCurentDistanceToTheMoon()
