import streamlit as st
import requests
import time
import xml.etree.ElementTree as ET

# --- [バージョン定義] ---
VERSION = "V1.1.0"

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
        res = requests.get(ITUNES_URL, params=params)
        results = res.json().get("results", [])
        if not results: return None
        
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
                album_list.append({
                    "exact_track": track_data.get("trackName"),
                    "exact_artist": track_data.get("artistName"),
                    "album_name": album_name,
                    "artwork_url": track_data.get("artworkUrl100").replace("100x100bb", "400x400bb"),
                    "preview_url": track_data.get("previewUrl")
                })
                
        return album_list[:max_display] if album_list else None
    except: return None

def fetch_from_rakuten_2026(album_keyword, artist_name, app_id, access_key):
    """2026年最新仕様に準拠し、正確なキー(makerCode)と備考欄データを抽出する関数"""
    clean_title = album_keyword.split(" - ")[0].split(" (")[0]
    
    params = {
        "applicationId": app_id,
        "accessKey": access_key,
        "title": clean_title,
        "artistName": artist_name,
        "format": "json",
        "hits": 3,
        "sort": "standard"
    }
    headers = {
        "Origin": "https://trycloudflare.com",
        "User-Agent": "Mozilla/5.0-CDChecker"
    }
    try:
        res = requests.get(RAKUTEN_URL, params=params, headers=headers)
        if res.status_code != 200: return None
        
        data = res.json()
        items = data.get("Items", [])
        
        cd_info_list = []
        for item_wrapper in items:
            item = item_wrapper.get("Item", {})
            cd_num = item.get("makerCode") or item.get("salesCode") or "（型番なし）"
            
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
        return {"data": cd_info_list, "raw": data}
    except: return None

def fetch_from_ndl(keyword, artist_name):
    """楽天で全滅した際に、国立国会図書館(NDL)のアーカイブを簡易探索する関数"""
    clean_title = keyword.split(" - ")[0].split(" (")[0]
    
    params = {
        "any": f"{artist_name} {clean_title}"
    }
    try:
        res = requests.get(NDL_URL, params=params, timeout=5)
        if res.status_code != 200: return None
        
        root = ET.fromstring(res.content)
        ndl_items = []
        
        for item in root.findall('.//item'):
            title = item.find('title').text if item.find('title') is not None else "不明"
            link = item.find('link').text if item.find('link') is not None else "#"
            desc = item.find('description').text if item.find('description') is not None else "詳細情報なし"
            
            ndl_items.append({
                "title": title,
                "url": link,
                "desc": desc
            })
        return {"data": ndl_items, "raw_xml": res.text}
    except:
        return None

# --- [Streamlit 画面構成セクション] ---
st.set_page_config(page_title="楽曲のCD番号 チェッカー", page_icon="💿", layout="centered")

st.title("💿 楽曲のCD番号 チェッカー")
st.write("アーティスト名と曲名を入力すると、appleのデータベース及び楽天APIからCD番号他主要データを表示します")

# 【新機能】隠し金庫（st.secrets）に鍵があれば自動適用、なければこれまでのデフォルト値を割り当てる
secret_app_id = st.secrets.get("RAKUTEN_APP_ID", "1944c4fa-f957-4985-a6d2-02d3ad38f477")
secret_access_key = st.secrets.get("RAKUTEN_ACCESS_KEY", "")

st.sidebar.header("🔑 楽天APIキー設定")
input_app_id = st.sidebar.text_input("アプリケーションID (UUID)", value=secret_app_id, type="password")
input_access_key = st.sidebar.text_input("アクセスキー (pk_...)", value=secret_access_key, type="password")

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

col1, col2 = st.columns(2)
with col1:
    user_track = st.text_input("🎵 曲名を入力", placeholder="例: Lemon")
with col2:
    user_artist = st.text_input("👤 アーティスト名を入力", placeholder="例: 米津玄師")

if st.button("検索を開始する", type="primary"):
    if not input_app_id or not input_access_key:
        st.error("左側のサイドバーに「アプリケーションID」と「アクセスキー」を入力してください。")
    elif not user_track or not user_artist:
        st.warning("曲名とアーティスト名の両方を入力してください。")
    else:
        with st.spinner("各データベースの深層を探索中..."):
            itunes_albums = fetch_multi_from_itunes(user_track, user_artist, filter_mode, max_display)
            st.markdown("---")
            
            if itunes_albums:
                st.subheader(f"✨ 配信確認アルバム ({len(itunes_albums)}件)")
                
                for idx, album in enumerate(itunes_albums, 1):
                    st.markdown(f"### 📦 エントリー [{idx}]: {album['album_name']}")
                    
                    left_col, right_col = st.columns([1, 2])
                    with left_col:
                        st.image(album["artwork_url"], use_container_width=True)
                    with right_col:
                        st.markdown(f"**楽曲正式名**: {album['exact_track']}")
                        st.markdown(f"**アーティスト**: {album['exact_artist']}")
                        st.audio(album["preview_url"], format="audio/m4a")
                        
                        time.sleep(0.3)
                        result = fetch_from_rakuten_2026(
                            album["album_name"], album["exact_artist"], 
                            input_app_id, input_access_key
                        )
                        
                        st.markdown("━━━━ **流通物理CD対応型番** ━━━━")
                        if result and "data" in result and result["data"]:
                            for cd_info in result["data"]:
                                st.markdown(f"💿 **{cd_info['cd_title']}**")
                                st.code(f"{cd_info['cd_number']}", language="text")
                                st.caption(cd_info["note"])
                                st.caption(f"流通価格: {cd_info['price']}円 | [楽天で詳細を見る]({cd_info['url']})")
                                
                            if debug_mode:
                                st.markdown("🛠️ **楽天API 生レスポンスデータ**")
                                st.json(result.get("raw", {}))
                        else:
                            st.caption("🌐 対応する物理CD型番が見つかりません。配信限定リリースか、CDが廃盤になっている可能性があります。")
                            
                            if debug_mode and result:
                                st.markdown("🛠️ **楽天API 生レスポンスデータ**")
                                st.json(result.get("raw", {}))
                                
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
                st.info("⚠️ デジタル配信データは見つかりませんでした。物理CDデータベースを直接検索します。")
                time.sleep(0.3)
                result = fetch_from_rakuten_2026(user_track, user_artist, input_app_id, input_access_key)
                
                if result and "data" in result and result["data"]:
                    for idx, info in enumerate(result["data"], 1):
                        st.markdown(f"**[{idx}] {info['cd_title']}**")
                        st.code(f"{info['cd_number']}", language="text")
                        st.caption(info["note"])
                        
                    if debug_mode:
                        st.markdown("🛠️ **楽天API 生レスポンスデータ**")
                        st.json(result.get("raw", {}))
                else:
                    st.caption("🌐 対応する物理CD型番が見つかりません。配信限定リリースか、CDが廃盤になっている可能性があります。")
                    
                    if debug_mode and result:
                        st.markdown("🛠️ **楽天API 生レスポンスデータ**")
                        st.json(result.get("raw", {}))
                        
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
