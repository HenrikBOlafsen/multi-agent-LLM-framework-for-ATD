import random
import country

cities = ["Oslo", "London", "Madrid", "Berlin", "Beograd", "Rome", "Paris"]
citiyCountry = {"Oslo": "Norway", "London": "England", "Madrid": "Spain", "Berlin": "Germany", "Beograd": "Serbia", "Rome": "Italy", "Paris": "France"}

def getRandomCity():
    return random.choice(cities)

def getCityCountry(city: str):
    return citiyCountry[str.capitalize(city)]

def getCityInformation(city: str):
    city = str.capitalize(city)
    countryOfCity = getCityCountry(city)
    countryPopulation = country.getCountryPopulation(countryOfCity)
    return "The city " + city + " is in " + getCityCountry(city) + ". " + countryOfCity + " has a population of " +  str(countryPopulation)

def getCityCountryList():
    return citiyCountry

def getLanguageOfCity():
    return country.getLanguageOfCountry()