# PyRoOrbforCOIAS

PyRoOrbを導入したうえで、これをCOIASユーザーが手軽に動かせるようにするための自作スクリプト群。

PyRoOrbディレクトリ内、PyRoOrb直下にscripts、dataフォルダを作り、
data 内に更にinput,outputフォルダを作っておく想定。

各スクリプト内で他のスクリプトも参照するので、pyファイルは全て同じscriptsディレクトリ内にダウンロード必須。
input内にitf.txt を保存しておく。

初回動作時のみitfのSQLを構築するので時間がかかるが、2回目以降はスキップされるので速くなる。
ただしitfを更新したらもう一度勝手に構築し直しを始める。

＊仮符号リストから検索
dkbkさんの　https://github.com/dkbk/misc_coias　
で作ったCOIASastファイルの仮符号をdesignaton.txtとしておくと、その中に書き込まれた仮符号天体を上から順にITFサーチしてDES-ITFを探してくれる。仮符号リストは圧縮だろうが非圧縮だろうが、ほかに余計な文字列が入っていようがそのまま使用可能。
./.venv/bin/python scripts/search_designation_list.py \
    --itf data/input/itf.txt \
    --list-file data/input/designations.txt

ちなみに仮符号天体の観測はそのつどMPCにAPIで勝手に取ってきてくれるので、ITFと違い事前の手動ダウンロード不要。

＊heliolincかtracklet-listから検索
https://github.com/Mira-Ao/heliolincforCOIAS　
で作ったheliolincで同一天体判定を受けたトラックレット群について、追加のITFサーチを行うのが--cluster-file。
または2夜存在するパーソナル符号名を列挙したり、H000000 = H000001 のようにペアで結び付けたトラックレットも1群としてITFサーチを行えるのが--tracklet-list。
つまりトラックレット群をあたかも1つの仮符号天体のように扱ってDES-ITFっぽいことができる。（もちろん実際はITF-ITF）
./.venv/bin/python scripts/search_unidentified.py \
    --itf data/input/itf.txt \
    --cluster-file data/input/finalout_itfMPC80.txt \
    --tracklet-list data/input/tracklet_names.txt

cluster-fileかtracklet-listはどちらか1つでいい。


以上2つは、リンクが見つかればlinkageファイルを出してくれる。
ついでにフィッティングして確かめる用の観測ファイルも。

また以上2つは、
    --start-index 50 \
    --limit 50
のような引数指定ができ、リスト内の天体やクラスターにつき分割実施できる。
上の表示だと、51件目から再開し50件進める（つまり51～100）。

未同定の回収
heliolincの出力ファイルを1か所（heliolinc_clusters）に集めて動かすと、その中のまだ同定が受け付けられていないクラスター（つまりITFに残っているクラスター）をひとまとめにしてくれる、上の作業の補助コード。
./.venv/bin/python scripts/collect_remaining_clusters.py \
  --input-dir data/input/heliolinc_clusters \
  --output-dir data/output/remaining_itf_clusters


＊その他
出力されるlinkageファイルのメアドと名前をデフォルトで入力するには、PyRorb > src > pyroorb > itf >config.py の1594行目あたりの

submit_email: str = field(default_factory=lambda: _env("ITF_SUBMIT_EMAIL", ""))
submit_name: str = field(default_factory=lambda: _env("ITF_SUBMIT_NAME", ""))

を

submit_email: str = field(default_factory=lambda: _env("ITF_SUBMIT_EMAIL", "your@email.com"))
submit_name: str = field(default_factory=lambda: _env("ITF_SUBMIT_NAME", "A. Manaka"))

とかに変えます。
