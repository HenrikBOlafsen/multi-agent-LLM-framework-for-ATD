import textUpgrader

def announceNumber(number: int):
    return textUpgrader.addDashesAboveAndBelowText(textUpgrader.addDashesToText("Your number is " + str(number) + "!"))

def numberInfo(number: int):
    isEvenText = "" if (number % 2) == 0 else "not "
    isBigNumberText = "" if number > 100 else "not "
    return "Your number " + str(number) + " is " + isEvenText + "even and is " + isBigNumberText + "a very big number"