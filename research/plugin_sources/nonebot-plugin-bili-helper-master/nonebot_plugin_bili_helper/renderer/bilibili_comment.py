import json
import os

DIRNAME = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(DIRNAME)

class BilibiliCommentRenderer:
    template_list = [
        '/resources/template/bilibili/html/comment.html',
        '/resources/template/extend/html/default.html',
    ]

    script_lists = [
        '/resources/libs/template-web.js',
        '/resources/render-v2/@libs/scripts.js',
        '/resources/render-v2/@libs/renderer.js',
        '/resources/render-v2/@formatters/bilibili.js',
    ]

    template = '/resources/render-v2/bilibili/comment.html'

    @staticmethod
    def take_placeholders(html: str, id: str, content: str) -> str:
        return html.replace(f'<placeholder id="{id}"></placeholder>', content)

    @staticmethod
    def render_html(video_info: dict, comments: list):
        # 读取模板文件
        template_path = os.path.join(ROOT_DIR, BilibiliCommentRenderer.template.lstrip('/'))
        with open(template_path, 'r', encoding='utf-8') as f:
            html = f.read()

        # 插入模板列表
        template_list_html = ''
        for template in BilibiliCommentRenderer.template_list:
            template_path = os.path.join(ROOT_DIR, template.lstrip('/'))
            with open(template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
            id = json.dumps(template, ensure_ascii=False)
            text = json.dumps(template_content, ensure_ascii=False).replace('</script>', '<\\/script>')
            template_list_html += f'<script>\nScriptsModule.createScript({{ id: {id}, type: "text/html", content: {text} }});\n</script>\n'
        html = BilibiliCommentRenderer.take_placeholders(html, 'template_list', template_list_html)

        # 插入脚本列表
        script_list_html = ''
        for script in BilibiliCommentRenderer.script_lists:
            script_path = os.path.join(ROOT_DIR, script.lstrip('/'))
            script_list_html += f'<script type="text/javascript" src="{script_path}"></script>\n'
        html = BilibiliCommentRenderer.take_placeholders(html, 'scripts_list', script_list_html)

        # 插入页面数据
        page_data = {
            'videoInfo': video_info,
            'comments': comments,
        }
        page_data_html = f'<script type="application/json" id="page_data">{json.dumps(page_data, ensure_ascii=False)}</script>\n'
        html = BilibiliCommentRenderer.take_placeholders(html, 'page_data', page_data_html)

        # 插入资源路径
        res_path = os.path.join(ROOT_DIR, 'resources') + '/'
        res_path_html = f'<script type="text/plain" id="res_path">{res_path}</script>\n'
        html = BilibiliCommentRenderer.take_placeholders(html, 'res_path', res_path_html)

        return html
