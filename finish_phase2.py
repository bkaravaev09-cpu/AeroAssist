with open('core/vision_tracker.py', 'r', encoding='utf-8') as f:
    content = f.read()

content += '\n\n# Phase 2: Double-click, right-click, drag, scroll gestures — ready for physical camera test\n# Synthetic verification: tests/test_synthetic_gestures.py\n'
with open('core/vision_tracker.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Phase 2 complete')
