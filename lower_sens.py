with open('core/cursor_controller.py', 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace('sensitivity: float = 1.9', 'sensitivity: float = 1.2')
c = c.replace('smoothing: float = 0.74', 'smoothing: float = 0.85')
with open('core/cursor_controller.py', 'w', encoding='utf-8') as f:
    f.write(c)
print('Lowered to 1.2 + smoother 0.85')
