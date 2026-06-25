import streamlit as st
import requests
import urllib.parse
import xml.etree.ElementTree as ET

# --- [バージョン定義] ---
VERSION = "V1.7.0"

# --- [定数・API URLの設定] ---
I_DOM = "itunes." + "apple.com"
ITUNES_URL = "https://" + I_DOM + "/search"
RAKUTEN_URL = "https://openapi.rakuten.co.jp/services/api/BooksCD/Search/20170404"
NDL_URL = "https://ndlsearch.ndl.go.jp/api/opensearch"
DDG_URL = "https://api.duckduckgo.com/"

# --- [セッションステート初期化] ---
for key, default in [("track_val", ""), ("artist_val", "")]:
    if key not in st.session_state:
        st.session_state[key] = default

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

    # クエリ2: 曲名 + アーティスト名（曲名とアルバム名が異なる場合のみ）
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


def _ndl_fetch_raw(params):
    """NDL OpenSearchへの実際のHTTPリクエスト（内部共通処理）"""
    try:
        res = requests.get(NDL_URL, params=params, timeout=5)
        if res.status_code != 200:
            return None, None
        root = ET.fromstring(res.content)
        return root, res.text
    except requests.exceptions.RequestException as e:
        st.error(f"NDL API 通信エラー: {e}")
        return None, None
    except Exception as e:
        st.error(f"NDL API 予期しないエラー: {e}")
        return None, None


def _parse_ndl_items(root):
    """NDLレスポンスからアイテムリストを生成（内部共通処理）"""
    if root is None:
        return []
    ndl_items = []
    seen_urls = set()
    for item in root.findall('.//item'):
        title_el = item.find('title')
        link_el = item.find('link')
        desc_el = item.find('description')
        url = link_el.text if link_el is not None else "#"
        if url in seen_urls:
            continue
        seen_urls.add(url)
        ndl_items.append({
            "title": title_el.text if title_el is not None else "不明",
            "url": url,
            "desc": desc_el.text if desc_el is not None else "詳細情報なし"
        })
    return ndl_items


def fetch_from_ndl(album_keyword, artist_name, track_name=""):
    """音楽CD絞り込み＋アルバム名・曲名の2クエリマージでNDLを探索する関数"""
    clean_album = album_keyword.split(" - ")[0].split(" (")[0]
    base_params = {"mediatype": "6"}

    # クエリ1: アーティスト名 + アルバム名
    params_album = {**base_params, "any": f"{artist_name} {clean_album}"}
    root_album, xml_album = _ndl_fetch_raw(params_album)
    items_album = _parse_ndl_items(root_album)

    # クエリ2: アーティスト名 + 曲名（曲名とアルバム名が異なる場合のみ）
    items_track = []
    if track_name and track_name.lower() != clean_album.lower():
        params_track = {**base_params, "any": f"{artist_name} {track_name}"}
        root_track, _ = _ndl_fetch_raw(params_track)
        items_track = _parse_ndl_items(root_track)

    # マージ（URL重複除去）
    seen_urls = {item["url"] for item in items_album}
    merged = list(items_album)
    for item in items_track:
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            merged.append(item)

    return {"data": merged, "raw_xml": xml_album or ""} if merged else {"data": [], "raw_xml": xml_album or ""}


def fetch_ddg_cd_candidates(track_name, artist_name):
    """DuckDuckGo非公式APIでCD番号候補を検索する（実験的機能）"""
    query = f"{artist_name} {track_name} CD 規格品番"
    params = {
        "q": query,
        "format": "json",
        "no_redirect": "1",
        "no_html": "1",
        "skip_disambig": "1"
    }
    try:
        res = requests.get(DDG_URL, params=params, timeout=8)
        if res.status_code != 200:
            return None
        data = res.json()

        candidates = []

        # AbstractText（トップ要約）
        if data.get("AbstractText"):
            candidates.append({
                "title": data.get("Heading", "概要"),
                "snippet": data["AbstractText"],
                "url": data.get("AbstractURL", "#")
            })

        # RelatedTopics（関連トピック）
        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                candidates.append({
                    "title": topic.get("Text", "")[:40] + "...",
                    "snippet": topic.get("Text", ""),
                    "url": topic.get("FirstURL", "#")
                })

        return candidates if candidates else None

    except requests.exceptions.RequestException:
        return None
    except Exception:
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


def render_rakuten_miss(album_name, artist_name, track_name, rakuten_result, debug_mode, input_app_id, input_access_key):
    """楽天ヒット0のときの共通表示処理（DDG候補 → NDL）"""
    st.caption("🌐 対応する物理CD型番が楽天では見つかりませんでした。")

    # DuckDuckGo CD番号候補（実験的）
    st.markdown("🦆 **DuckDuckGo検索によるCD番号の候補** _(実験的機能)_")
    ddg_results = fetch_ddg_cd_candidates(track_name, artist_name)
    if ddg_results:
        for item in ddg_results:
            st.info(f"**{item['title']}**\n\n{item['snippet']}")
            if item["url"] != "#":
                st.caption(f"[参照元を確認する]({item['url']})")
    else:
        st.caption("DuckDuckGoからも候補が見つかりませんでした。")

    if debug_mode and rakuten_result:
        st.markdown("🛠️ **楽天API 生レスポンスデータ**")
        st.json(rakuten_result.get("raw", {}))

    st.markdown("🏛️ **国立国会図書館の所蔵アーカイブを自動探索中...**")
    ndl_result = fetch_from_ndl(album_name, artist_name, track_name=track_name)

    if ndl_result and ndl_result["data"]:
        for n_idx, n_item in enumerate(ndl_result["data"][:2], 1):
            st.warning(f"国立国会図書館ヒット [{n_idx}]: {n_item['title']}")
            st.caption(f"[国会図書館の該当ページで型番を確認する]({n_item['url']})")
    else:
        st.caption("❌ 国会図書館の公開検索システムにも該当する所蔵データがありませんでした。")

    if debug_mode and ndl_result:
        st.markdown("🛠️ **国立国会図書館API 生リクエストXMLデータ**")
        st.code(ndl_result.get("raw_xml", ""), language="xml")


# --- [Streamlit 画面構成セクション] ---
st.set_page_config(page_title="楽曲のCD番号 チェッカー", page_icon="💿", layout="centered")

st.title("💿 楽曲のCD番号 チェッカー")
st.write("アーティスト名と曲名を入力すると、Appleのデータベース及び楽天APIからCD番号他主要データを表示します")

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

# ── 入力欄（keyなし・session_stateで直接管理）+ クリアボタン ──
col_track, col_track_clear = st.columns([5, 1])
with col_track:
    user_track = st.text_input("🎵 曲名を入力", value=st.session_state["track_val"], placeholder="例: Lemon")
with col_track_clear:
    st.write("")
    if st.button("🗑️", key="clear_track", help="曲名をクリア"):
        st.session_state["track_val"] = ""
        st.rerun()

col_artist, col_artist_clear = st.columns([5, 1])
with col_artist:
    user_artist = st.text_input("👤 アーティスト名を入力", value=st.session_state["artist_val"], placeholder="例: 米津玄師")
with col_artist_clear:
    st.write("")
    if st.button("🗑️", key="clear_artist", help="アーティスト名をクリア"):
        st.session_state["artist_val"] = ""
        st.rerun()

# 入力値をsession_stateに保存（次のrerunで引き継ぐ）
st.session_state["track_val"] = user_track
st.session_state["artist_val"] = user_artist

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

                            matched_items = [cd for cd in all_cd_items if cd["cd_title"].lower() == apple_album_lower]
                            for cd_info in matched_items:
                                st.markdown(f"💿 **{cd_info['cd_title']}**")
                                st.code(f"{cd_info['cd_number']}", language="text")
                                st.caption(cd_info["note"])
                                st.caption(f"流通価格: {cd_info['price']}円 | [楽天で詳細を見る]({cd_info['url']})")

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
                            render_rakuten_miss(
                                album["album_name"], album["exact_artist"], album["exact_track"],
                                rakuten_result, debug_mode, input_app_id, input_access_key
                            )

                    st.markdown("---")

            else:
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
                    render_rakuten_miss(
                        user_track, user_artist, user_track,
                        rakuten_result, debug_mode, input_app_id, input_access_key
                    )
