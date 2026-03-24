def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

def multiply(a, b):
    return a * b

def divide(a, b):
    # intentionally missing validation for Copilot to catch
    return a / b

def modulo(a, b):
    return a % b

def calculate(operation, a, b):
    if operation == "add":
        return add(a, b)
    elif operation == "subtract":
        return subtract(a, b)
    elif operation == "multiply":
        return multiply(a, b)
    elif operation == "divide":
        return divide(a, b)
    elif operation == "modulo":
        return modulo(a, b)

result = calculate("divide", 10, 0)
print(result)
