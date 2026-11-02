with open('core/visual_calibration.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('        current_step = STEPS[step]\n', '        # Using STEPS[step] for display\n')

with open('core/visual_calibration.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed unused variable')
