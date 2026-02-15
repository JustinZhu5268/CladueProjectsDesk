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


def escape_js_string(text: str) -> str:
    """Escape string for safe JavaScript embedding."""
    if not isinstance(text, str):
        text = str(text)
    # 顺序很重要：先转义反斜杠，再转义其他
    return (text
        .replace("\\", "\\\\")  # 必须先转义反斜杠
        .replace("'", "\\'")     # 单引号
        .replace('"', '\\"')     # 双引号
        .replace("\n", "\\n")    # 换行
        .replace("\r", "")       # 回车删除
        .replace("</script>", "<\\/script>"))  # 防止闭合script


def get_chat_html_template(dark_mode: bool = True) -> str:
    """Generate chat HTML template with embedded JavaScript."""
    colors = {
        "bg": "#1E1E1E" if dark_mode else "#FFFFFF",
        "text": "#E5E5E5" if dark_mode else "#1A1A1A",
        "user_bg": "#2A3A4A" if dark_mode else "#E8F0FE",
        "assist_bg": "#2D2D2D" if dark_mode else "#F8F8F8",
        "code_bg": "#1A1A1A" if dark_mode else "#F5F5F5",
        "meta": "#888888",
        "uid": "#666666"
    }
    
    # 使用%s占位符避免f-string转义地狱
    html_template = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style type="text/css">
body { 
    font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif; 
    background: %(bg)s; 
    color: %(text)s; 
    margin: 0; 
    padding: 20px; 
    line-height: 1.6; 
}
.message { 
    margin: 12px 0; 
    padding: 12px 16px; 
    border-radius: 12px; 
    max-width: 85%%; 
    word-wrap: break-word; 
    position: relative; 
}
.user { 
    background: %(user_bg)s; 
    margin-left: auto; 
    text-align: right; 
}
.assistant { 
    background: %(assist_bg)s; 
    margin-right: auto; 
}
.meta { 
    font-size: 11px; 
    color: %(meta)s; 
    margin-top: 6px; 
    cursor: pointer; 
}
.uid { 
    font-family: Consolas, monospace; 
    font-size: 10px; 
    color: %(uid)s; 
    margin-left: 8px; 
}
pre { 
    background: %(code_bg)s; 
    padding: 12px; 
    border-radius: 6px; 
    overflow-x: auto; 
}
code { 
    font-family: "Cascadia Code", Consolas, monospace; 
}
#stream { 
    display: none; 
    background: %(assist_bg)s; 
}
</style>
</head>
<body>
<div id="chat"></div>
<div id="stream" class="message assistant">
    <span id="stream-text"></span>
    <span style="opacity:0.5;">&#9646;</span>
</div>

<script type="text/javascript">
// Global message storage
var messageStore = {};

// Core function: Add a message to chat
function addMessage(role, htmlContent, metaInfo, uid) {
    var chatContainer = document.getElementById('chat');
    var msgDiv = document.createElement('div');
    msgDiv.className = 'message ' + role;
    
    if (uid && uid.length > 0) {
        msgDiv.id = 'msg-' + uid;
    }
    
    msgDiv.innerHTML = htmlContent;
    
    // Add metadata line
    if (metaInfo || uid) {
        var metaDiv = document.createElement('div');
        metaDiv.className = 'meta';
        
        var metaText = metaInfo || '';
        if (uid && uid.length > 0) {
            metaText += '<span class="uid">#' + uid.substring(0, 8) + '</span>';
            messageStore[uid] = {
                role: role,
                content: htmlContent,
                meta: metaInfo
            };
        }
        
        metaDiv.innerHTML = metaText;
        msgDiv.appendChild(metaDiv);
    }
    
    chatContainer.appendChild(msgDiv);
    window.scrollTo(0, document.body.scrollHeight);
    return true;
}

// Start streaming mode
function startStreaming() {
    var streamDiv = document.getElementById('stream');
    streamDiv.style.display = 'block';
    document.getElementById('stream-text').innerHTML = '';
    window.scrollTo(0, document.body.scrollHeight);
}

// Append text during streaming
function appendStreamText(htmlContent) {
    document.getElementById('stream-text').innerHTML = htmlContent;
    window.scrollTo(0, document.body.scrollHeight);
}

// Finish streaming and add final message
function finishStreaming(htmlContent, metaInfo, uid) {
    document.getElementById('stream').style.display = 'none';
    addMessage('assistant', htmlContent, metaInfo, uid);
}

// Add error message
function addError(errorMsg) {
    var chatContainer = document.getElementById('chat');
    var errorDiv = document.createElement('div');
    errorDiv.style.cssText = 'color:#E74C3C;background:#FADBD8;padding:10px;border-radius:6px;margin:10px 0;';
    errorDiv.textContent = errorMsg;
    chatContainer.appendChild(errorDiv);
    window.scrollTo(0, document.body.scrollHeight);
}

// Clear all messages
function clearChat() {
    document.getElementById('chat').innerHTML = '';
    messageStore = {};
}

// Expose to window for safety
window.addMessage = addMessage;
window.startStreaming = startStreaming;
window.appendStreamText = appendStreamText;
window.finishStreaming = finishStreaming;
window.addError = addError;
window.clearChat = clearChat;
</script>
</body>
</html>""" % colors
    
    return html_template