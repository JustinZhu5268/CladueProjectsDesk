import sqlite3
import os

# 检查数据库
conn = sqlite3.connect(r'C:\Users\Think\ClaudeStation\claude_station.db')
cursor = conn.cursor()

# 检查 conversations 表中的 rolling_summary
cursor.execute('SELECT id, title, rolling_summary, last_compressed_msg_id, summary_token_count, compress_after_turns FROM conversations')
print("=== Conversations with Summary ===")
for row in cursor.fetchall():
    conv_id, title, rolling_summary, last_compressed, summary_count, compress_after = row
    print(f"ID: {conv_id}")
    print(f"  Title: {title}")
    print(f"  rolling_summary: {rolling_summary[:100] if rolling_summary else 'EMPTY'}...")
    print(f"  last_compressed_msg_id: {last_compressed}")
    print(f"  summary_token_count: {summary_count}")
    print(f"  compress_after_turns: {compress_after}")
    print()

# 检查 messages 表结构
print("\n=== Messages Table Info ===")
cursor.execute("PRAGMA table_info(messages)")
for row in cursor.fetchall():
    print(row)

# 检查是否有 uid 或 copy 相关的列
cursor.execute("SELECT id, role, content FROM messages LIMIT 5")
print("\n=== Sample Messages ===")
for row in cursor.fetchall():
    msg_id, role, content = row
    print(f"ID: {msg_id}, Role: {role}, Content: {content[:50]}...")

conn.close()
