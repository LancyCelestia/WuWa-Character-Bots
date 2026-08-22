import json
import os

DIRNAME = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(DIRNAME)

import sys
sys.path.append(ROOT_DIR)
from renderer.bilibili_comment import BilibiliCommentRenderer

build_dir = os.path.join(ROOT_DIR, 'build')
os.makedirs(build_dir, exist_ok=True)

video_info_path = os.path.join(ROOT_DIR, 'resources/mocks/bilibili/video_info.json')
comments_path = os.path.join(ROOT_DIR, 'resources/mocks/bilibili/comments.json')

with open(video_info_path, 'r', encoding='utf-8') as f:
    video_info = json.load(f)

with open(comments_path, 'r', encoding='utf-8') as f:
    comments = json.load(f)

html = BilibiliCommentRenderer.render_html(video_info, comments)
output_path = os.path.join(build_dir, 'bilibili_comment.html')
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(html)

print(f'Rendered HTML saved to: {output_path}')
