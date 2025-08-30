import random
import math
from textWriter import announceNumber

def randomlyIncreaseNumber(number: int):
    return number + random.random() * 100

def makeNumberMultipleOf5(number: int):
    return math.floor(number) - math.floor(number)%5

def makeNumberWithProperties(minValue: int, maxValue: int, divisibleBy: int):
    if divisibleBy == 0:
        raise ValueError("divisible_by cannot be zero")
    
    # Find the smallest multiple of `divisible_by` within range
    start = (minValue + divisibleBy - 1) // divisibleBy * divisibleBy  # Ceiling division
    end = (maxValue // divisibleBy) * divisibleBy  # Floor division
    
    if start > maxValue:  # No valid number exists
        raise ValueError("No valid number exists in the given range")

    return random.randint(start // divisibleBy, end // divisibleBy) * divisibleBy

def numberToSentence(number: int):
    return announceNumber(number)