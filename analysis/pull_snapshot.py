import os
from anki.collection import Collection
from wordfreq import word_frequency
from dataclasses import dataclass
import seaborn as sns
import matplotlib.pyplot as plt
from gensim.models.fasttext import load_facebook_vectors
from pathlib import Path
import pandas as pd
import umap

import logging

logger = logging.getLogger(__file__)

@dataclass
class AnkiCardStudyStats:
    word: str
    total_reviews: int
    num_again: int
    avg_time_s: float
    
def x_from_df(df:pd.DataFrame, col:str='Embedding') -> pd.DataFrame:
    cols = ['E'+str(x) for x in np.arange(0,len(df[col].iloc[0]))]
    return pd.DataFrame(df[col].tolist(), columns=cols, index=df.index)

if __name__ == "__main__":
    logger.info("start loading facebook vectors")
    HOME = Path(__file__).parents[1]
    wv = load_facebook_vectors(HOME / "models" / "cc.de.300.bin")
    logger.info("loaded")
    os.makedirs("snapshot/users/kuya/", exist_ok=True)
    col = Collection("snapshot/users/kuya/collection.anki2")      # 必须是全新的空文件
    if False:
        auth = col.sync_login("kuya", "20201015", "http://raspberrypi.local:8080/")
        col.sync_collection(auth, False)
        col.close_for_full_sync()
        col.full_upload_or_download(auth=auth, server_usn=None, upload=False)  # 只下载，绝不上传
        col.reopen(after_full_sync=True)

    rows = col.db.all("""
    select n.sfld, count(*) as reviews, sum(r.ease = 1) as again,
            round(avg(r.time)/1000.0, 1) as avg_sec, c.lapses, c.ivl
    from revlog r
    join cards c on c.id = r.cid
    join notes n on n.id = c.nid
    where r.type != 4
    group by c.id
    order by again desc
    """)
    
    data = []
    for row in rows:
        word = row[0].replace("(B2)", "").replace("der", "").replace("die", "").replace("das", "").strip()
        data.append({"word": word, "freq": word_frequency(word, "de"), "embedding": wv[word]})
    
    df = pd.DataFrame(data)
    
    print(sorted(data, key=lambda x: x["freq"], reverse=True))
    
    figure, ax = plt.subplots(figsize=(6, 6))
    sns.stripplot([record["freq"] for record in data], ax=ax)
    plt.show()
    