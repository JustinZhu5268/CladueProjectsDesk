import sqlite3
import os
from pathlib import Path

# 检查可能的数据库位置
db_paths = [
    r"C:\Users\Think\ClaudeStation\claude_station.db",
    r"C:\Users\Think\ClaudeStation\claude_station\claude_station.db",
    r"C:\Users\Think\Desktop\ClaudeStation\claude_station\claude_station.db",
]

print("=== 检查数据库文件 ===")
for path in db_paths:
    if os.path.exists(path):
        size = os.path.getsize(path)
        mtime = os.path.getmtime(path)
        print(f"Found: {path}")
        print(f"  Size: {size} bytes")
        print(f"  Modified: {mtime}")
    else:
        print(f"Not found: {path}")

print("\n=== 检查默认位置的数据库 ===")
default_db = r"C:\Users\Think\ClaudeStation\claude_station.db"
if os.path.exists(default_db):
    conn = sqlite3.connect(default_db)
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    print("Tables:", [r[0] for r in cursor.fetchall()])
    
    cursor.execute("SELECT COUNT(*) FROM projects")
    print(f"Projects: {cursor.fetchone()[0]}")
    
    cursor.execute("SELECT id, name FROM projects")
    for row in cursor.fetchall():
        print(f"  - {row[0]}: {row[1]}")
    
    cursor.execute("SELECT COUNT(*) FROM conversations")
    print(f"Conversations: {cursor.fetchone()[0]}")
    
    conn.close()
else:
    print(f"Default DB not found: {default_db}")

# 检查代码中的数据库路径
print("\n=== 检查代码中的数据库配置 ===")
config_path = r"C:\Users\Think\Desktop\ClaudeStation\claude_station\config.py"
with open(config_path, "r", encoding="utf-8") as f:
    content = f.read()
    for line in content.split("\n"):
        if "DB_PATH" in line or "DATA_DIR" in line:
            print(line.strip())
