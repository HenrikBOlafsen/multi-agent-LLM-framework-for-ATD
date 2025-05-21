import numberModifiers
import textWriter
from city import getRandomCity, getCityInformation
from country import getRandomCountry, getCountryInformation
from textPadder import getpaddedNumberList

def mainFunction():
    myNumber = numberModifiers.makeNumberMultipleOf5(numberModifiers.randomlyIncreaseNumber(0))
    myOtherNumber = numberModifiers.makeNumberMultipleOf5(numberModifiers.randomlyIncreaseNumber(myNumber))
    print(textWriter.announceNumber(myNumber))
    print(textWriter.announceNumber(myOtherNumber))
    print(textWriter.numberInfo(myNumber))
    print(textWriter.numberInfo(myOtherNumber))

    print("Here are 10 numbers between those numbers that are divisible by 3:")
    print(getpaddedNumberList(myNumber, myOtherNumber, 3))

    print()
    
    myCity = getRandomCity()

    print(getCityInformation(myCity))

    myCountry = getRandomCountry()
    print(getCountryInformation(myCountry))




mainFunction()