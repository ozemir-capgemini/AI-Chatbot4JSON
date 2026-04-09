lines = open('generate_report.py').readlines()
for i in range(145, 175):
    print(f'{i+1}: {lines[i]}', end='')
