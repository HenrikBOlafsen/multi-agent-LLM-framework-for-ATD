import city
import random

countryPopulation = {
    "Norway": 5520000,
    "England": 56500000,
    "Spain": 48350000,
    "Germany": 83280000,
    "Serbia": 6623000,
    "Italy": 59000000,
    "France": 68290000
}

def getRandomCountry():
    return random.choice(list(countryPopulation.keys()))

def getCountryPopulation(country: str):
    return countryPopulation[str.capitalize(country)]

def getCapitalOfCountry(country: str):
    cityCountryList = city.getCityCountryList()
    inv_map = {v: k for k, v in cityCountryList.items()}
    return inv_map[country]

def getCountryInformation(country: str):
    return "The country " + country + " has a population of " + str(getCountryPopulation(country)) + " and the capital is " + getCapitalOfCountry(country)

def getLanguageOfCountry():
    return city.getLanguageOfCity()