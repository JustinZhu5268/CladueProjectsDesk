import sqlite3

conn = sqlite3.connect(r'C:\Users\Think\ClaudeStation\claude_station.db')
cursor = conn.cursor()

cursor.execute('SELECT id, name, created_at, updated_at FROM projects ORDER BY created_at DESC')
print('All projects:')
rows = cursor.fetchall()
print(f'Count: {len(rows)}')
for row in rows:
    print(row)

cursor.execute('SELECT COUNT(*) FROM conversations')
print('\nConversations count:', cursor.fetchone()[0])

cursor.execute('SELECT id, title, project_id FROM conversations ORDER BY created_at DESC')
print('\nAll conversations:')
conv_rows = cursor.fetchall()
print(f'Count: {len(conv_rows)}')
for row in conv_rows:
    print(row)

cursor.execute('SELECT COUNT(*) FROM messages')
print('\nMessages count:', cursor.fetchone()[0])

conn.close()
