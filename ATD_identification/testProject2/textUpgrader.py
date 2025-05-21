from textPadder import padTextTopBottom

def addDashesToText(text: str):
    return "--- " + text

def addDashesAboveAndBelowText(text: str):
    return padTextTopBottom("------------------------------------------\n" + text + "\n------------------------------------------")