"""Files the wasm pygame build on the pygame-web CDN is missing.

``pygame_patch/pygame/`` holds the pure-python modules that build dropped from
the wasm wheel.  ``shardlight.core.pygame_bootstrap`` copies them into the
installed package before pygame is imported.
"""
