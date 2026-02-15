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
        "code_border": "#404040" if dark_mode else "#E0E0E0",
        "meta": "#888888",
        "uid": "#666666",
        "copy_btn_bg": "#4A4A4A",
        "copy_btn_hover": "#5A5A5A",
    }
    
    # 使用%s占位符避免f-string转义地狱
    html_template = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style type="text/css">
body { 
    font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif; 
    font-size: 14px; 
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
    font-size: 14px; 
}
.message h1 { font-size: 1.35em; margin: 0.5em 0 0.35em 0; }
.message h2 { font-size: 1.2em; margin: 0.45em 0 0.3em 0; }
.message h3 { font-size: 1.1em; margin: 0.4em 0 0.25em 0; }
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
    font-family: Consolas, "Cascadia Code", monospace; 
    font-size: 11px; 
    font-weight: 500; 
    color: %(uid)s; 
    margin-left: 8px; 
    padding: 2px 6px; 
    border-radius: 4px; 
    background: rgba(128,128,128,0.2); 
}
.uid-link { 
    cursor: pointer; 
}
.uid-link:hover { text-decoration: underline; }

/* 代码块独立区域样式 */
.code-block-wrapper {
    position: relative;
    margin: 12px 0;
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid %(code_border)s;
}

.code-block-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: %(code_bg)s;
    padding: 6px 12px;
    border-bottom: 1px solid %(code_border)s;
    font-size: 12px;
    color: #888;
}

.code-block-header .code-lang {
    font-family: "Cascadia Code", Consolas, monospace;
}

.code-block-copy-btn {
    background: %(copy_btn_bg)s;
    color: #CCC;
    border: none;
    padding: 4px 10px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 11px;
    transition: background 0.2s;
}

.code-block-copy-btn:hover {
    background: %(copy_btn_hover)s;
}

.code-block-copy-btn.copied {
    background: #2E7D32;
    color: white;
}

.code-block-wrapper pre { 
    background: %(code_bg)s; 
    padding: 12px; 
    margin: 0;
    overflow-x: auto; 
}
code { 
    font-family: "Cascadia Code", Consolas, monospace; 
}
#stream { 
    display: none; 
    background: %(assist_bg)s; 
}

/* Markdown 下载按钮样式 */
.msg-copy-btn:hover {
    background: #5A5A5A;
}
</style>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
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

// 处理代码块：为每个代码块添加复制按钮
function processCodeBlocks() {
    var chatContainer = document.getElementById('chat');
    var preBlocks = chatContainer.querySelectorAll('pre');
    
    // 使用 for 循环兼容更多浏览器
    for (var i = 0; i < preBlocks.length; i++) {
        var pre = preBlocks[i];
        // 检查是否已经处理过
        if (pre.dataset && pre.dataset.processed) continue;
        if (pre.dataset) pre.dataset.processed = 'true';
        
        // 获取代码语言
        var codeBlock = pre.querySelector('code');
        var lang = '';
        if (codeBlock && codeBlock.className && codeBlock.className.indexOf('language-') !== -1) {
            lang = codeBlock.className.replace('language-', '').replace('highlight', '').trim();
        }
        
        // 创建包装器
        var wrapper = document.createElement('div');
        wrapper.className = 'code-block-wrapper';
        
        // 创建头部
        var header = document.createElement('div');
        header.className = 'code-block-header';
        
        var langSpan = document.createElement('span');
        langSpan.className = 'code-lang';
        langSpan.textContent = lang || 'code';
        header.appendChild(langSpan);
        
        var copyBtn = document.createElement('button');
        copyBtn.className = 'code-block-copy-btn';
        copyBtn.textContent = '复制代码';
        
        // 保存当前元素的引用，避免闭包问题
        (function() {
            var currentPre = pre;
            var currentBtn = copyBtn;
            copyBtn.onclick = function() {
                var codeText = currentPre.textContent || currentPre.innerText || '';
                copyToClipboard(codeText, currentBtn);
            };
        })();
        header.appendChild(copyBtn);
        
        // 将 pre 包装到 wrapper 中
        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(header);
        wrapper.appendChild(pre);
    }
}

// 复制到剪贴板
function copyToClipboard(text, btn) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function() {
            showCopiedFeedback(btn);
        }).catch(function() {
            fallbackCopy(text, btn);
        });
    } else {
        fallbackCopy(text, btn);
    }
}

function fallbackCopy(text, btn) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    try { 
        document.execCommand('copy'); 
        showCopiedFeedback(btn);
    } catch (e) {
        btn.textContent = '复制失败';
    }
    document.body.removeChild(ta);
}

function showCopiedFeedback(btn) {
    btn.textContent = '已复制!';
    btn.classList.add('copied');
    setTimeout(function() {
        btn.textContent = '复制代码';
        btn.classList.remove('copied');
    }, 2000);
}

// Core function: Add a message to chat
function addMessage(role, htmlContent, metaInfo, uid, rawMarkdown) {
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
        metaDiv.innerHTML = metaText;
        if (uid && uid.length > 0) {
            // 优先使用原始 Markdown，如果没有则从 HTML 提取
            var storeContent = rawMarkdown && rawMarkdown.length > 0 ? rawMarkdown : htmlContent;
            messageStore[uid] = {
                role: role,
                content: storeContent,  // 存储 HTML 或原始 Markdown
                meta: metaInfo,
                isRawMarkdown: rawMarkdown && rawMarkdown.length > 0  // 标记是否是原始 Markdown
            };
            var uidSpan = document.createElement('span');
            uidSpan.className = 'uid uid-link';
            uidSpan.setAttribute('data-uid', uid);
            uidSpan.textContent = '#' + uid.substring(0, 8);
            uidSpan.title = 'Click to reference in input';
            uidSpan.onclick = function() {
                if (window.chatHost) window.chatHost.insertRef('@#' + uid);
            };
            metaDiv.appendChild(uidSpan);
            
            // Copy message button
            var copyBtn = document.createElement('span');
            copyBtn.className = 'msg-copy-btn';
            copyBtn.textContent = '复制';
            copyBtn.title = '复制消息';
            copyBtn.style.cssText = 'cursor:pointer;margin-left:10px;padding:2px 8px;background:#666;color:#fff;border-radius:3px;font-size:11px;';
            copyBtn.onclick = function(e) {
                e.stopPropagation();
                copyMessageText(uid);
            };
            metaDiv.appendChild(copyBtn);
        }
        msgDiv.appendChild(metaDiv);
    }
    
    chatContainer.appendChild(msgDiv);
    
            // 处理代码块（添加复制按钮）
            setTimeout(function() {
                try {
                    processCodeBlocks();
                } catch (e) {
                    // 静默处理错误，不影响消息显示
                }
            }, 100);
    
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
function finishStreaming(htmlContent, metaInfo, uid, rawMarkdown) {
    document.getElementById('stream').style.display = 'none';
    addMessage('assistant', htmlContent, metaInfo, uid, rawMarkdown);
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

// Copy message text to clipboard
function copyMessageText(uid) {
    var entry = messageStore[uid];
    if (!entry || !entry.content) return;
    var div = document.createElement('div');
    div.innerHTML = entry.content;
    var text = div.innerText || div.textContent || '';
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function() {}).catch(function() {});
    } else {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); } catch (e) {}
        document.body.removeChild(ta);
    }
}

// Clear all messages
function clearChat() {
    document.getElementById('chat').innerHTML = '';
    messageStore = {};
}

// Expose to window for safety
window.addMessage = addMessage;
window.copyMessageText = copyMessageText;
window.startStreaming = startStreaming;
window.appendStreamText = appendStreamText;
window.finishStreaming = finishStreaming;
window.addError = addError;
window.clearChat = clearChat;
</script>
</body>
</html>""" % colors
    
    return html_template