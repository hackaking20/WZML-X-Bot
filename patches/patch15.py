import sys

with open(sys.argv[1], 'r') as f:
    content = f.read()

if 'STREAM_PASS' in content:
    print("ALREADY PATCHED bot_settings.py: STREAM_PASS exists")
    sys.exit(0)

# 1. Add STREAM_PASS description to DEFAULT_DESP
old_desp = '    "STREAM_TOKENS": "Bot tokens dedicated to /stream and /dl. If set, streaming uses these and is isolated from mirror/leech load. Falls back to HELPER_TOKENS.",\n'
new_desp = '    "STREAM_TOKENS": "Bot tokens dedicated to /stream and /dl. If set, streaming uses these and is isolated from mirror/leech load. Falls back to HELPER_TOKENS.",\n    "STREAM_PASS": "Password for user-account stream access (?user=1). Viewers must enter this to stream via your personal account. Leave empty to disable user-stream auth.",\n'
content = content.replace(old_desp, new_desp, 1)

# 2. Add STREAM_PASS to PROTECTED_VARS
old_protected = 'PROTECTED_VARS = {\n    "TELEGRAM_HASH",\n    "TELEGRAM_API",\n    "OWNER_ID",\n    "BOT_TOKEN",\n    "DATABASE_URL",\n}'
new_protected = 'PROTECTED_VARS = {\n    "TELEGRAM_HASH",\n    "TELEGRAM_API",\n    "OWNER_ID",\n    "BOT_TOKEN",\n    "DATABASE_URL",\n    \n}'
content = content.replace(old_protected, new_protected, 1)

with open(sys.argv[1], 'w') as f:
    f.write(content)

print("PATCHED bot_settings.py: added STREAM_PASS to DEFAULT_DESP (Reset enabled)")
