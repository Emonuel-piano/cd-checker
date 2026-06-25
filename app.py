import streamlit as st
import requests
import urllib.parse
import xml.etree.ElementTree as ET

# --- [バージョン定義] ---
VERSION = "V1.5.1"

# --- [定数・API URLの設定] ---
I_DOM = "itunes." + "apple.com"
ITUNES_URL = "https://" + I_DOM + "/search"
RAKUTEN_URL = "https://openapi.rakuten.co.jp/services/api/BooksCD/Search/20170404"
NDL_URL = "https://ndlsearch.ndl.go.jp/api/opensearch"

# --- [データ取得関数] ---
def fetch_multi_from_itunes(track_name, artist_name, filter_mode, max_display):
    """iTunes APIからアルバム情報を取得し、選ばれた感度と表示上限数で仕分ける"""
    params = {
        "term": f"{artist_name} {track_name}",
        "country": "jp",
        "media": "music",
        "entity": "song",
        "limit": 30
    }
    try:
        res = requests.get(ITUNES_URL, params=params, timeout=10)
        res.raise_for_status()
        results = res.json().get("results", [])
        if not results:
            return None

        first_artist = results[0].get("artistName", "").lower()
        first_track = results[0].get("trackName", "")
        core_track = first_track.split(" (")[0].split(" - ")[0].lower().strip()

        album_list = []
        seen_albums = set()

        for track_data in results:
            current_artist = track_data.get("artistName", "").lower()
            current_track = track_data.get("trackName", "").lower()
            album_name = track_data.get("collectionName")

            if filter_mode != "🟢 フィルター無し":
                if first_artist[:3] not in current_artist and current_artist[:3] not in first_artist:
                    continue

            if filter_mode == "🔴 きつめ":
                if core_track not in current_track and current_track not in core_track:
                    continue

            if album_name and album_name not in seen_albums:
                seen_albums.add(album_name)
                artwork_raw = track_data.get("artworkUrl100") or ""
                artwork_url = artwork_raw.replace("100x100bb", "400x400bb") if artwork_raw else ""
                album_list.append({
                    "exact_track": track_data.get("trackName", "不明"),
                    "exact_artist": track_data.get("artistName", "不明"),
                    "album_name": album_name,
                    "track_number": track_data.get("trackNumber"),
                    "track_count": track_data.get("trackCount"),
                    "artwork_url": artwork_url,
                    "preview_url": track_data.get("previewUrl") or ""
                })

        return album_list[:max_display] if album_list else None

    except requests.exceptions.RequestException as e:
        st.error(f"iTunes API 通信エラー: {e}")
        return None
    except Exception as e:
        st.error(f"iTunes API 予期しないエラー: {e}")
        return None


def _rakuten_fetch_raw(params, headers):
    """楽天APIへの実際のHTTPリクエスト（内部共通処理）"""
    try:
        res = requests.get(RAKUTEN_URL, params=params, headers=headers, timeout=10)
        if res.status_code != 200:
            return None
        return res.json()
    except requests.exceptions.RequestException as e:
        st.error(f"楽天API 通信エラー: {e}")
        return None
    except Exception as e:
        st.error(f"楽天API 予期しないエラー: {e}")
        return None


def _parse_rakuten_items(data):
    """楽天APIレスポンスからCD情報リストを生成（内部共通処理）"""
    cd_info_list = []
    seen_cd_numbers = set()
    for item_wrapper in data.get("Items", []):
        item = item_wrapper.get("Item", {})
        cd_num = item.get("makerCode") or item.get("salesCode") or "（型番なし）"
        if cd_num in seen_cd_numbers:
            continue
        seen_cd_numbers.add(cd_num)
        label = item.get("label", "不明")
        jan = item.get("jan", "不明")
        release_date = item.get("salesDate", "不明")
        note_text = f"🏢 レーベル: {label} | 📦 JAN: {jan} | 📅 発売日: {release_date}"
        cd_info_list.append({
            "cd_number": cd_num,
            "cd_title": item.get("title", "タイトル不明"),
            "price": item.get("itemPrice", 0),
            "url": item.get("itemUrl", "#"),
            "note": note_text
        })
    return cd_info_list


def fetch_from_rakuten_2026(album_keyword, artist_name, app_id, access_key, track_name=""):
    """アルバム名＋アーティスト名、曲名＋アーティスト名の2クエリで検索しマージして返す"""
    clean_album = album_keyword.split(" - ")[0].split(" (")[0]
    headers = {
        "Origin": "https://trycloudflare.com",
        "User-Agent": "Mozilla/5.0-CDChecker"
    }
    base_params = {
        "applicationId": app_id,
        "accessKey": access_key,
        "artistName": artist_name,
        "format": "json",
        "hits": 8,
        "sort": "standard"
    }

    # クエリ1: アルバム名 + アーティスト名
    params_album = {**base_params, "title": clean_album}
    data_album = _rakuten_fetch_raw(params_album, headers)
    items_album = _parse_rakuten_items(data_album) if data_album else []

    # クエリ2: 曲名 + アーティスト名（曲名が渡された場合のみ）
    data_track = None
    items_track = []
    if track_name and track_name.lower() != clean_album.lower():
        params_track = {**base_params, "title": track_name}
        data_track = _rakuten_fetch_raw(params_track, headers)
        items_track = _parse_rakuten_items(data_track) if data_track else []

    # マージ（cd_number重複除去、アルバム名検索結果を優先）
    seen = {cd["cd_number"] for cd in items_album}
    merged = list(items_album)
    for cd in items_track:
        if cd["cd_number"] not in seen:
            seen.add(cd["cd_number"])
            merged.append(cd)

    raw_combined = {"query_album": data_album, "query_track": data_track}
    return {"data": merged, "raw": raw_combined} if merged else {"data": [], "raw": raw_combined}


def fetch_from_ndl(keyword, artist_name):
    """楽天で全滅した際に、国立国会図書館(NDL)のアーカイブを簡易探索する関数"""
    clean_title = keyword.split(" - ")[0].split(" (")[0]
    params = {"any": f"{artist_name} {clean_title}"}
    try:
        res = requests.get(NDL_URL, params=params, timeout=5)
        if res.status_code != 200:
            return None

        root = ET.fromstring(res.content)
        ndl_items = []
        for item in root.findall('.//item'):
            title_el = item.find('title')
            link_el = item.find('link')
            desc_el = item.find('description')
            ndl_items.append({
                "title": title_el.text if title_el is not None else "不明",
                "url": link_el.text if link_el is not None else "#",
                "desc": desc_el.text if desc_el is not None else "詳細情報なし"
            })
        return {"data": ndl_items, "raw_xml": res.text}

    except requests.exceptions.RequestException as e:
        st.error(f"NDL API 通信エラー: {e}")
        return None
    except Exception as e:
        st.error(f"NDL API 予期しないエラー: {e}")
        return None


def render_search_assist(track_name, artist_name):
    """入力欄直下に常時表示する検索補助セクション"""
    st.markdown("---")
    st.markdown("#### 🔍 さらに詳しく調べる")
    query_text = f"{artist_name} {track_name} CD 番号 型番"
    ai_question = f"{artist_name}の「{track_name}」について、収録アルバム名・何曲目に入っているか・CDの規格品番をできるだけ詳しく教えてください。"
    google_url = "https://www.google.com/search?q=" + urllib.parse.quote(query_text)
    perplexity_url = "https://www.perplexity.ai/search?q=" + urllib.parse.quote(ai_question)

    col_g, col_p = st.columns(2)
    with col_g:
        st.link_button("🔎 Googleで検索する", google_url, use_container_width=True)
        st.caption(f"検索ワード: `{query_text}`")
    with col_p:
        st.link_button("🤖 Perplexityに相談する（無料・アカウント不要）", perplexity_url, use_container_width=True)
        st.caption("アルバム・トラック番号・CD型番をAIに質問")
    st.markdown("---")


# --- [Streamlit 画面構成セクション] ---
st.set_page_config(page_title="楽曲のCD番号 チェッカー", page_icon="💿", layout="centered")

st.title("💿 楽曲のCD番号 チェッカー")
st.write("アーティスト名と曲名を入力すると、Appleのデータベース及び楽天APIからCD番号他主要データを表示します")

# セッションステート初期化（クリアボタン用）
if "track_input" not in st.session_state:
    st.session_state["track_input"] = ""
if "artist_input" not in st.session_state:
    st.session_state["artist_input"] = ""

input_app_id = st.secrets.get("RAKUTEN_APP_ID", "1944c4fa-f957-4985-a6d2-02d3ad38f477")
input_access_key = st.secrets.get("RAKUTEN_ACCESS_KEY", "")

st.sidebar.markdown("---")
st.sidebar.header("🎯 フィルター感度調整")
filter_mode = st.sidebar.radio(
    "検索結果の間口を調整できます：",
    ["🟢 フィルター無し", "🟡 標準", "🔴 きつめ"],
    index=1
)

st.sidebar.markdown("---")
st.sidebar.header("📊 表示件数の上限")
max_display = st.sidebar.slider(
    "何件まで候補を表示しますか？",
    min_value=1, max_value=20, value=6, step=1
)

debug_mode = st.sidebar.checkbox("⚙️ 各APIの生データを表示（デバッグ）※開発者用")

st.sidebar.markdown("---")
st.sidebar.caption(f"App Version: {VERSION}")

# 入力欄 + クリアボタン
col_track, col_track_clear = st.columns([5, 1])
with col_track:
    user_track = st.text_input("🎵 曲名を入力", placeholder="例: Lemon", key="track_input")
with col_track_clear:
    st.write("")
    if st.button("🗑️", key="clear_track", help="曲名をクリア"):
        st.session_state["track_input"] = ""
        st.rerun()

col_artist, col_artist_clear = st.columns([5, 1])
with col_artist:
    user_artist = st.text_input("👤 アーティスト名を入力", placeholder="例: 米津玄師", key="artist_input")
with col_artist_clear:
    st.write("")
    if st.button("🗑️", key="clear_artist", help="アーティスト名をクリア"):
        st.session_state["artist_input"] = ""
        st.rerun()

# ── 検索補助セクション（入力欄直下・常時表示） ──
if user_track and user_artist:
    render_search_assist(user_track, user_artist)

if st.button("検索を開始する", type="primary"):
    if not input_app_id or not input_access_key:
        st.error("管理画面のSecretsに「アプリケーションID」と「アクセスキー」を設定してください。")
    elif not user_track or not user_artist:
        st.warning("曲名とアーティスト名の両方を入力してください。")
    else:
        with st.spinner("各データベースの深層を探索中..."):
            itunes_albums = fetch_multi_from_itunes(user_track, user_artist, filter_mode, max_display)
            st.markdown("---")

            if itunes_albums:
                st.subheader(f"✨ 配信確認アルバム ({len(itunes_albums)}件)")

                if debug_mode:
                    st.markdown("🛠️ **Apple Music API 生レスポンスデータ**")
                    st.json(itunes_albums)

                for idx, album in enumerate(itunes_albums, 1):
                    st.markdown(f"### 📦 エントリー [{idx}]: {album['album_name']}")

                    left_col, right_col = st.columns([1, 2])
                    with left_col:
                        if album["artwork_url"]:
                            st.image(album["artwork_url"], use_container_width=True)
                    with right_col:
                        st.markdown(f"**楽曲正式名**: {album['exact_track']}")
                        st.markdown(f"**アーティスト**: {album['exact_artist']}")
                        track_num = album.get("track_number")
                        track_count = album.get("track_count")
                        if track_num:
                            track_info = f"{track_num}曲目"
                            if track_count:
                                track_info += f" / 全{track_count}曲"
                            st.markdown(f"**収録位置**: {track_info}")
                        if album["preview_url"]:
                            st.audio(album["preview_url"], format="audio/m4a")

                        # ── 楽天API検索（2クエリマージ） ──
                        rakuten_result = fetch_from_rakuten_2026(
                            album["album_name"], album["exact_artist"],
                            input_app_id, input_access_key,
                            track_name=album["exact_track"]
                        )

                        st.markdown("━━━━ **流通物理CD対応型番** ━━━━")

                        if rakuten_result and rakuten_result.get("data"):
                            apple_album_lower = album["album_name"].lower()
                            all_cd_items = rakuten_result["data"]

                            # アルバム名一致分を先に表示
                            matched_items = [cd for cd in all_cd_items if cd["cd_title"].lower() == apple_album_lower]
                            for cd_info in matched_items:
                                st.markdown(f"💿 **{cd_info['cd_title']}**")
                                st.code(f"{cd_info['cd_number']}", language="text")
                                st.caption(cd_info["note"])
                                st.caption(f"流通価格: {cd_info['price']}円 | [楽天で詳細を見る]({cd_info['url']})")

                            # 楽天にしかない追加CDを表示
                            new_cd_items = [cd for cd in all_cd_items if cd["cd_title"].lower() != apple_album_lower]
                            if new_cd_items:
                                st.caption("📦 楽天APIで見つかった追加CD:")
                                for cd_info in new_cd_items:
                                    st.markdown(f"💿 **{cd_info['cd_title']}**")
                                    st.code(f"{cd_info['cd_number']}", language="text")
                                    st.caption(cd_info["note"])
                                    st.caption(f"流通価格: {cd_info['price']}円 | [楽天で詳細を見る]({cd_info['url']})")

                            if debug_mode:
                                st.markdown("🛠️ **楽天API 生レスポンスデータ**")
                                st.json(rakuten_result.get("raw", {}))

                        else:
                            # 楽天ヒット0 → NDLへ（Apple Musicの二重表示はしない）
                            st.caption("🌐 対応する物理CD型番が楽天では見つかりませんでした。")

                            if debug_mode and rakuten_result:
                                st.markdown("🛠️ **楽天API 生レスポンスデータ**")
                                st.json(rakuten_result.get("raw", {}))

                            st.markdown("🏛️ **国立国会図書館の所蔵アーカイブを自動探索中...**")
                            ndl_result = fetch_from_ndl(album["album_name"], album["exact_artist"])

                            if ndl_result and ndl_result["data"]:
                                for n_idx, n_item in enumerate(ndl_result["data"][:2], 1):
                                    st.warning(f"国立国会図書館ヒット [{n_idx}]: {n_item['title']}")
                                    st.caption(f"[国会図書館の該当ページで型番を確認する]({n_item['url']})")
                            else:
                                st.caption("❌ 国会図書館の公開検索システムにも該当する所蔵データがありませんでした。")

                            if debug_mode and ndl_result:
                                st.markdown("🛠️ **国立国会図書館API 生リクエストXMLデータ**")
                                st.code(ndl_result.get("raw_xml", ""), language="xml")

                    st.markdown("---")

            else:
                # iTunes全滅 → 楽天を直接検索
                st.info("⚠️ デジタル配信データは見つかりませんでした。物理CDデータベースを直接検索します。")
                rakuten_result = fetch_from_rakuten_2026(user_track, user_artist, input_app_id, input_access_key, track_name=user_track)

                if rakuten_result and rakuten_result.get("data"):
                    for idx, info in enumerate(rakuten_result["data"], 1):
                        st.markdown(f"**[{idx}] {info['cd_title']}**")
                        st.code(f"{info['cd_number']}", language="text")
                        st.caption(info["note"])

                    if debug_mode:
                        st.markdown("🛠️ **楽天API 生レスポンスデータ**")
                        st.json(rakuten_result.get("raw", {}))

                else:
                    st.caption("🌐 対応する物理CD型番が見つかりません。配信限定リリースか、CDが廃盤になっている可能性があります。")

                    if debug_mode and rakuten_result:
                        st.markdown("🛠️ **楽天API 生レスポンスデータ**")
                        st.json(rakuten_result.get("raw", {}))

                    st.markdown("🏛️ **国立国会図書館の所蔵アーカイブを自動探索中...**")
                    ndl_result = fetch_from_ndl(user_track, user_artist)

                    if ndl_result and ndl_result["data"]:
                        for n_idx, n_item in enumerate(ndl_result["data"][:3], 1):
                            st.warning(f"国立国会図書館ヒット [{n_idx}]: {n_item['title']}")
                            st.caption(f"[国会図書館の該当ページで型番を確認する]({n_item['url']})")
                    else:
                        st.error("❌ 配信・物理CD・国会図書館のいずれからも該当楽曲を特定できませんでした。")

                    if debug_mode and ndl_result:
                        st.markdown("🛠️ **国立国会図書館API 生リクエストXMLデータ**")
                        st.code(ndl_result.get("raw_xml", ""), language="xml")
