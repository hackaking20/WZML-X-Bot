import sys

# patch12 is now a no-op.
# Previously it injected _streamAuth JS stub, patched stream URLs with
# auth tokens, and handled 401 responses. All auth removed per user request.
# stream.html is used as-is from the WZML-X upstream.

print("PATCH 12: no-op (auth removed, stream.html unchanged)")
