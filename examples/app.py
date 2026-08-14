"""A plain script — no witness imports, no decorators. Capture it with:

    witness run --target legacy app.py
    witness generate

Then run the generated tests, or `witness check` after you change legacy.py.
"""

import legacy

print(legacy.slugify("Hello There, Friend!"))
print(legacy.parse_kv("host=localhost; port=8080"))
print(legacy.median([5, 3, 9, 1, 7]))
print(legacy.word_count("witness records what really happened"))
print(legacy.make_token("bob"))
