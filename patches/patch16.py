import sys

with open(sys.argv[1], 'r') as f:
    content = f.read()

if 'DIRECT' in content and '_userQ' in content and 'encodeURIComponent(TOKEN) + _userQ' in content:
    # Check if DIRECT already has _userQ
    if 'var DIRECT = location.origin + "/dl/" + encodeURIComponent(TOKEN) + _userQ' in content:
        print("ALREADY PATCHED stream.html: DIRECT has _userQ")
        sys.exit(0)

# Fix 1: Add _userQ to DIRECT (download) URL
old_direct = 'var DIRECT = location.origin + "/dl/" + encodeURIComponent(TOKEN);'
new_direct = 'var DIRECT = location.origin + "/dl/" + encodeURIComponent(TOKEN) + _userQ;'

if old_direct in content:
    content = content.replace(old_direct, new_direct, 1)
    print("PATCHED stream.html: added _userQ to DIRECT (download) URL")
else:
    # Maybe DIRECT is defined differently, try a broader match
    print("WARNING: could not find DIRECT variable in stream.html")
    # Try to find it
    import re
    m = re.search(r'var DIRECT\s*=\s*location\.origin\s*\+\s*"/dl/"\s*\+\s*encodeURIComponent\(TOKEN\)\s*;', content)
    if m:
        content = content[:m.start()] + new_direct + content[m.end():]
        print("PATCHED stream.html: added _userQ to DIRECT (download) URL via regex")
    else:
        print("ERROR: DIRECT variable not found at all")
        sys.exit(1)

# Fix 2: Also add _userQ to POSTER URL (for consistency)
old_poster = 'var POSTER = location.origin + "/poster/" + encodeURIComponent(TOKEN);'
new_poster = 'var POSTER = location.origin + "/poster/" + encodeURIComponent(TOKEN) + _userQ;'

if old_poster in content:
    content = content.replace(old_poster, new_poster, 1)
    print("PATCHED stream.html: added _userQ to POSTER URL")

with open(sys.argv[1], 'w') as f:
    f.write(content)
