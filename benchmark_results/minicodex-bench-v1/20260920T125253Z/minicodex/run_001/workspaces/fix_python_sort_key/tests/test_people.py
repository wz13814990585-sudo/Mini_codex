from src.people import names_by_age
def test_basic(): assert names_by_age([{'name':'B','age':2},{'name':'A','age':1}])==['A','B']
