with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove incorrectly placed calibration block at very top (before imports or after imports but outside class)
# Find the bad block and remove it
start = content.find('def _update_calibration_ui(self):')
if start != -1:
    # Find end of calibration block - up to where class starts again or imports end
    # Actually let's just find the bad content and delete it
    end = content.find('def _update_calibration_ui(self):', start+1)
    # This is messy; instead just delete from start to where class method starts properly
    # The easiest fix: find the first occurrence of calibration and delete up to "class AeroAssistApp"
    class_pos = content.find('class AeroAssistApp')
    # Actually the calibration code seems to be at top level, let's just delete lines 1-55 if they contain calibration
    lines = content.split('\n')
    new_lines = []
    skip_until_class = False
    for line in lines:
        if 'def _update_calibration_ui' in line:
            skip_until_class = True
        if skip_until_class and 'class AeroAssistApp' in line:
            skip_until_class = False
        if not skip_until_class:
            new_lines.append(line)
    content = '\n'.join(new_lines)

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Cleaned bad calibration placement')
