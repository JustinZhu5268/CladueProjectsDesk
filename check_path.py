from pathlib import Path
import os

# 模拟代码中的路径
APP_NAME = 'ClaudeStation'
USERPROFILE = os.environ.get('USERPROFILE', '~')
DATA_DIR = Path(USERPROFILE) / APP_NAME
DB_PATH = DATA_DIR / 'claude_station.db'

print(f'USERPROFILE: {USERPROFILE}')
print(f'DATA_DIR: {DATA_DIR}')
print(f'DB_PATH: {DB_PATH}')
print(f'DB_PATH absolute: {DB_PATH.resolve()}')
print(f'DB_PATH parent: {DB_PATH.parent}')
db_name = 'claude_station.db'
print(f'DB_PATH parent / db: {DB_PATH.parent / db_name}')
print(f'Are they equal? {str(DB_PATH) == str(DB_PATH.parent / db_name)}')
print()

# 检查实际文件
print('Actual files:')
for p in [DB_PATH, DB_PATH.parent / db_name, Path('C:/Users/Think/ClaudeStation/claude_station.db')]:
    print(f'  {p}: exists={p.exists()}')
