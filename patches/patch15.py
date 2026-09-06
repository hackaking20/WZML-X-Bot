import sys

with open(sys.argv[1], 'r') as f:
    content = f.read()

if 'MAX_STREAM_VIEWERS' in content and 'PRIORITY_KEY' in content:
    print("ALREADY PATCHED bot_settings.py: MAX_STREAM_VIEWERS and PRIORITY_KEY exist")
    sys.exit(0)

# 1. Add MAX_STREAM_VIEWERS and PRIORITY_KEY descriptions to DEFAULT_DESP
# Insert after the STREAM_PASS line (which was added by the first run of this patch)
stream_pass_line = '    "STREAM_PASS": "Password for user-account stream access (?user=1). Viewers must enter this to stream via your personal account. Leave empty to disable user-stream auth.",\\n'

new_lines = stream_pass_line + '    "MAX_STREAM_VIEWERS": "Max concurrent stream connections (tabs) allowed at the same time. Default 3. Set to 0 for unlimited.",\\n    "PRIORITY_KEY": "Secret key for owner/VIP to bypass the stream limit. Append &pkey=SECRET to stream URL. Leave empty to disable.",\\n'

if stream_pass_line in content:
    content = content.replace(stream_pass_line, new_lines, 1)
else:
    # STREAM_PASS not yet added — add all three after STREAM_TOKENS
    old_token_line = '    "STREAM_TOKENS": "Bot tokens dedicated to /stream and /dl. If set, streaming uses these and is isolated from mirror/leech load. Falls back to HELPER_TOKENS.",\\n'
    all_new = old_token_line + '    "STREAM_PASS": "Password for user-account stream access (?user=1). Viewers must enter this to stream via your personal account. Leave empty to disable user-stream auth.",\\n    "MAX_STREAM_VIEWERS": "Max concurrent stream connections (tabs) allowed at the same time. Default 3. Set to 0 for unlimited.",\\n    "PRIORITY_KEY": "Secret key for owner/VIP to bypass the stream limit. Append &pkey=SECRET to stream URL. Leave empty to disable.",\\n'
    content = content.replace(old_token_line, all_new, 1)

# NOTE: Not adding anything to PROTECTED_VARS so all three settings keep their reset button.

with open(sys.argv[1], 'w') as f:
    f.write(content)

print("PATCHED bot_settings.py: added MAX_STREAM_VIEWERS and PRIORITY_KEY to DEFAULT_DESP")
