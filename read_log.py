import os
path = r'C:\Users\Think\ClaudeStation\claude_station.log'
lines = open(path, 'r', encoding='utf-8', errors='ignore').readlines()

# 查找错误日志
for line in lines[-300:]:
    if 'ERROR' in line or 'Exception' in line or 'Traceback' in line:
        print(line.strip())
