lines = open('generate_report.py').readlines()
new_bullet = [
    '    def bullet(self, items):\n',
    '        self.set_font("Helvetica", "", 10.5)\n',
    '        self.set_text_color(50, 50, 50)\n',
    '        for item in items:\n',
    '            self.multi_cell(0, 5.5, f"     - {item}")\n',
    '        self.ln(3)\n',
]
lines[49:57] = new_bullet
open('generate_report.py', 'w').writelines(lines)
print('Done')
