import sys
path = sys.argv[1]
with open(path, "r") as f:
    content = f.read()
old = "    async def get_pm_uids(self):\n        if self._return:\n            return\n        return"
new = "    async def get_pm_uids(self):\n        if self._return:\n            return []\n        return"
if old in content:
    content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)
    print("PATCHED db_handler.py: get_pm_uids returns [] instead of None")
else:
    print("WARNING: db_handler.py target not found")
