with open('core/visual_calibration.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('    timer_id = None\n', '')
c = c.replace('        timer_id = master_app.after(3000, lambda: advance())', '        master_app.after(3000, lambda: advance())')

with open('core/visual_calibration.py', 'w', encoding='utf-8') as f:
    f.write(c)
print('Fixed timer_id')
