import os, tempfile
os.environ["ANKI_DATA"] = tempfile.mkdtemp()   # 必须在 import main 之前