import sys
path = sys.argv[1]
with open(path, "r") as f:
    content = f.read()

old = """        msg = await client.get_messages(chat_id, msg_id)
        if msg is None or getattr(msg, "empty", False):
            _fid_cache.pop(key, None)
            raise StreamGone(f"msg {msg_id} missing from {chat_id}")"""

new = """        msg = None
        _bot_name = getattr(getattr(client, "me", None), "username", None) or client.name
        for _fid_attempt in range(3):
            try:
                msg = await client.get_messages(chat_id, msg_id)
            except Exception as _fid_err:
                LOGGER.warning(f"get_fid: client {ci} (@{_bot_name}) get_messages({chat_id}, {msg_id}) raised: {_fid_err}")
                msg = None
            if msg is not None and not getattr(msg, "empty", False):
                break
            LOGGER.warning(f"get_fid: client {ci} (@{_bot_name}) attempt {_fid_attempt+1}/3 - msg is None or empty")
            from asyncio import sleep as _fid_sleep
            await _fid_sleep(2)
        if msg is None or getattr(msg, "empty", False):
            _fid_cache.pop(key, None)
            LOGGER.error(f"StreamGone: client {ci} (@{_bot_name}) cannot read msg {msg_id} from chat {chat_id} after 3 attempts")
            raise StreamGone(f"msg {msg_id} missing from {chat_id}")"""

if old in content:
    content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)
    print("PATCHED tg_stream.py: added retry + diagnostic logging with bot username")
else:
    print("WARNING: tg_stream.py target block not found")
