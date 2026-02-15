"""Markdown to HTML rendering for chat display."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

def render_markdown(text: str) -> str:
    """Convert markdown text to styled HTML fragment."""
    try:
        import markdown
        from markdown.extensions.codehilite import CodeHiliteExtension
        from markdown.extensions.fenced_code import FencedCodeExtension
        from markdown.extensions.tables import TableExtension
        
        md = markdown.Markdown(
            extensions=[
                FencedCodeExtension(),
                CodeHiliteExtension(css_class="highlight", linenums=False, guess_lang=True),
                TableExtension(),
                "markdown.extensions.sane_lists",
            ],
            output_format="html",
        )
        html = md.convert(text)
        md.reset()
        return html
    except ImportError:
        log.warning("markdown library not available")
        import html as html_mod
        return f"<pre>{html_mod.escape(text)}</pre>"

def get_chat_html_template(dark_mode: bool = True) -> str:
    """Get the full HTML template for the chat WebEngineView."""
    bg = "#1E1E1E" if dark_mode else "#FFFFFF"
    text_color = "#E5E5E5" if dark_mode else "#1A1A1A"
    user_bg = "#2A3A4A" if dark_mode else "#E8F0FE"
    assist_bg = "#2D2D2D" if dark_mode else "#F8F8F8"
    code_bg = "#1A1A1A" if dark_mode else "#F5F5F5"
    
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
    body {{
        font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
        background: {bg};
        color: {text_color};
        margin: 0;
        padding: 20px;
        line-height: 1.6;
    }}
    .message {{
        margin: 12px 0;
        padding: 12px 16px;
        border-radius: 12px;
        max-width: 85%;
        word-wrap: break-word;
    }}
    .user {{
        background: {user_bg};
        margin-left: auto;
        text-align: right;
    }}
    .assistant {{
        background: {assist_bg};
        margin-right: auto;
    }}
    .meta {{
        font-size: 11px;
        color: #888;
        margin-top: 6px;
    }}
    pre {{
        background: {code_bg};
        padding: 12px;
        border-radius: 6px;
        overflow-x: auto;
    }}
    #stream {{
        display: none;
        background: {assist_bg};
    }}
</style>
</head>
<body>
<div id="chat"></div>
<div id="stream" class="message assistant">
    <span id="stream-text"></span><span style="opacity:0.5;">▌</span>
</div>

<script>
function addMessage(role, html, meta) {{
    const chat = document.getElementById('chat');
    const div = document.createElement('div');
    div.className = 'message ' + role;
    div.innerHTML = html;
    if (meta) {{
        const m = document.createElement('div');
        m.className = 'meta';
        m.textContent = meta;
        div.appendChild(m);
    }}
    chat.appendChild(div);
    window.scrollTo(0, document.body.scrollHeight);
}}

function startStreaming() {{
    const s = document.getElementById('stream');
    s.style.display = 'block';
    document.getElementById('stream-text').innerHTML = '';
    window.scrollTo(0, document.body.scrollHeight);
}}

function appendStreamText(html) {{
    document.getElementById('stream-text').innerHTML = html;
    window.scrollTo(0, document.body.scrollHeight);
}}

function finishStreaming(html, meta) {{
    document.getElementById('stream').style.display = 'none';
    addMessage('assistant', html, meta);
}}

function addError(msg) {{
    const chat = document.getElementById('chat');
    const div = document.createElement('div');
    div.style.cssText = 'color:#E74C3C;background:#FADBD8;padding:10px;border-radius:6px;margin:10px 0;';
    div.textContent = msg;
    chat.appendChild(div);
}}
</script>
</body>
</html>"""