"""Render the real terminal formatter to an SVG using labeled sample events."""
import html
import io
import os
from pathlib import Path
import re
import runpy
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP = runpy.run_path(str(ROOT / 'diffdigger'))


class TTY(io.StringIO):
    def isatty(self):
        return True


stream = TTY()
with patch.dict(os.environ, {'TERM': 'xterm-256color'}), patch.object(APP['time'], 'strftime', return_value='14:32:08'):
    os.environ.pop('NO_COLOR', None)
    terminal = APP['Terminal'](stream=stream, columns=94)
    terminal.start(Path.home() / 'projects' / 'demo-repo')
    before = 'export async function saveLesson(input) {\n  const timeout = 1000;\n  const payload = input;\n  return client.post("/lessons", payload, { timeout });\n}\n'
    after = 'export async function saveLesson(input) {\n  const timeout = 5000;\n  const payload = validateLesson(input);\n\n  if (!payload.title) {\n    throw new Error("A lesson needs a title");\n  }\n  return client.post("/lessons", payload, { timeout });\n}\n'
    terminal.file_event('src/lessons/save.ts', ((), before, None, ''), ((), after, None, ''))
    terminal.git_event(0, 'COMMIT 8fa421c9 · Validate lessons before saving')
    terminal.git_event(0, 'PUSH origin/main → 8fa421c9')

cell, line_height, margin = 9, 22, 24
lines = stream.getvalue().splitlines()
width, height = 94 * cell + margin * 2, (len(lines) + 2) * line_height + margin * 2
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
       '<title>Diffdigger terminal preview — sample events</title>',
       f'<rect width="{width}" height="{height}" rx="12" fill="#1a1b26"/>',
       f'<text x="{margin + 18}" y="{margin + 8}" fill="#848fae" font-family="sans-serif" font-size="12">TERMINAL PREVIEW · SAMPLE EVENTS</text>']
foreground, background, bold = '#c0caf5', '#1a1b26', False
for row, line in enumerate(lines):
    x, y = margin, margin + 24 + row * line_height
    for part in re.split(r'(\x1b\[[0-9;]*m)', line):
        if part.startswith('\x1b['):
            codes = [int(n) for n in part[2:-1].split(';') if n] or [0]
            index = 0
            while index < len(codes):
                code = codes[index]
                if code == 0:
                    foreground, background, bold = '#c0caf5', '#1a1b26', False
                elif code == 1:
                    bold = True
                elif code in (38, 48) and codes[index + 1] == 2:
                    color = '#' + ''.join(f'{value:02x}' for value in codes[index + 2:index + 5])
                    if code == 38:
                        foreground = color
                    else:
                        background = color
                    index += 4
                index += 1
            continue
        length = APP['cell_width'](part) * cell
        if background != '#1a1b26' and length:
            svg.append(f'<rect x="{x}" y="{y - 16}" width="{length}" height="{line_height}" fill="{background}"/>')
        if part and not part.isspace():
            svg.append(f'<text x="{x}" y="{y}" fill="{foreground}" font-family="JetBrains Mono,monospace" font-size="15" font-weight="{700 if bold else 400}" xml:space="preserve" textLength="{length}" lengthAdjust="spacingAndGlyphs">{html.escape(part)}</text>')
        x += length
svg.append('</svg>')
destination = ROOT / 'docs' / 'terminal.svg'
destination.parent.mkdir(exist_ok=True)
destination.write_text('\n'.join(svg) + '\n')
print(destination)
