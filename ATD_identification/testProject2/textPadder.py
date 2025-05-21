import numberModifiers

def padTextTopBottom(text: str):
    return "\n"+text+"\n"

def padList(textList: list[str]):
    finalText = ""
    for text in textList:
        finalText += text + "\n"
    return finalText[0:-2]

def getpaddedNumberList(minValue: int, maxValue: int, divisibleBy: int):
    return padList([str(numberModifiers.makeNumberWithProperties(minValue, maxValue, divisibleBy)) for _ in range(10)])