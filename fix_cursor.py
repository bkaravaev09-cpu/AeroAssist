with open('core/cursor_controller.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace('dead_zone: float = 2.0', 'dead_zone: float = 8.0')
content = content.replace('max_head_step: float = 0.20', 'max_head_step: float = 0.15')
with open('core/cursor_controller.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Cursor stability fixed')
