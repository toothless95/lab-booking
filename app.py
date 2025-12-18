import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import altair as alt
from streamlit_gsheets import GSheetsConnection

# ============================================================================
# 1. 설정 및 초기화
# ============================================================================
st.set_page_config(
    page_title="실험실 통합 예약 시스템", 
    layout="wide", 
    page_icon="🔬"
)

# [비밀번호 보안] secrets에서 가져오거나 기본값 사용
def get_password():
    if "admin_password" in st.secrets:
        return st.secrets["admin_password"]
    if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
        if "admin_password" in st.secrets["connections"]["gsheets"]:
            return st.secrets["connections"]["gsheets"]["admin_password"]
    return "admin1234"

ADMIN_PASSWORD = get_password()

# ============================================================================
# 2. 데이터 처리 및 클리닝 (핵심 기능 개선)
# ============================================================================

@st.cache_resource
def get_connection():
    return st.connection("gsheets", type=GSheetsConnection)

def clean_val(val):
    """
    [핵심] 데이터 클리닝 함수
    1. '1111.0' 같은 소수점 문자열을 '1111'로 변환 (비밀번호 오류 해결)
    2. None/NaN을 빈 문자열로 변환
    """
    s = str(val).strip()
    if s == 'nan' or s == 'None':
        return ""
    if s.endswith('.0'):
        return s[:-2]
    return s

def get_empty_structure(sheet_name):
    structures = {
        'labs': ['name'],
        'equipment': ['name'],
        'bookings': ['id', 'user_name', 'lab', 'equipment', 'date', 'start_time', 'end_time', 'password'],
        'water': ['date', 'user_name', 'lab', 'amount'],
        'logs': ['timestamp', 'action', 'user', 'details']
    }
    return pd.DataFrame(columns=structures.get(sheet_name, []))

@st.cache_data(ttl=60)
def load_sheet_cached(sheet_name):
    conn = get_connection()
    try:
        df = conn.read(worksheet=sheet_name, ttl=0) # 항상 최신 데이터 시도
        
        if df is None or df.empty or len(df.columns) == 0:
            return get_empty_structure(sheet_name)
        
        # 데이터 클리닝 (모든 셀에 대해 소수점 제거 및 문자열 변환 수행)
        df = df.astype(str).applymap(clean_val)
        
        # 필수 컬럼 확인
        req_cols = get_empty_structure(sheet_name).columns
        if not set(req_cols).issubset(df.columns):
            return get_empty_structure(sheet_name)
            
        return df
    except:
        return get_empty_structure(sheet_name)

def save_sheet(sheet_name, df):
    conn = get_connection()
    try:
        # 저장 전 한 번 더 클리닝
        df = df.fillna('').astype(str).applymap(clean_val)
        conn.update(worksheet=sheet_name, data=df)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"저장 실패: {e}")
        return False

def add_log(action, user, details):
    try:
        df_log = load_sheet_cached('logs')
        new_log = pd.DataFrame([{
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'action': action,
            'user': user,
            'details': details
        }])
        if df_log.empty: df_log = new_log
        else: df_log = pd.concat([df_log, new_log], ignore_index=True)
        save_sheet('logs', df_log)
    except: pass

# ============================================================================
# 3. 비즈니스 로직 (수정/삭제/중복체크)
# ============================================================================

def parse_time(time_str):
    if not time_str or len(time_str) != 4 or not time_str.isdigit(): return None
    h, m = int(time_str[:2]), int(time_str[2:])
    if not (0 <= h <= 23 and 0 <= m <= 59): return None
    return f"{h:02d}:{m:02d}"

def check_overlap(df, date_str, eq_name, start_time, end_time, exclude_id=None):
    """중복 체크 (수정 시 본인 ID 제외 기능 추가)"""
    if df.empty: return False, ""
    try:
        # 내 예약 제외 (수정 모드일 때 사용)
        if exclude_id:
            df = df[df['id'] != exclude_id].copy()
            
        same = df[(df['date'] == date_str) & (df['equipment'] == eq_name)]
        if same.empty: return False, ""
        
        for _, row in same.iterrows():
            # 문자열 비교 (HH:MM)
            r_start = str(row['start_time'])[:5]
            r_end = str(row['end_time'])[:5]
            
            if (r_start < end_time) and (r_end > start_time):
                return True, str(row['user_name'])
        return False, ""
    except:
        return False, ""

def calculate_hours(start_str, end_str):
    try:
        end_min = 24*60 if end_str == "24:00" else int(end_str.split(':')[0])*60 + int(end_str.split(':')[1])
        start_min = int(start_str.split(':')[0])*60 + int(start_str.split(':')[1])
        return (end_min - start_min) / 60.0
    except: return 0.0

def batch_update_name(target_type, old_name, new_name):
    """
    [핵심] 이름 변경 시 모든 데이터 일괄 업데이트
    target_type: 'lab' or 'equipment'
    """
    # 1. 중복 검사
    sheet_name = 'labs' if target_type == 'lab' else 'equipment'
    df_master = load_sheet_cached(sheet_name)
    
    if new_name in df_master['name'].values:
        return False, "이미 존재하는 이름입니다."
    
    # 2. 마스터 데이터 수정
    if old_name in df_master['name'].values:
        df_master.loc[df_master['name'] == old_name, 'name'] = new_name
        save_sheet(sheet_name, df_master)
    
    # 3. 예약 내역(bookings) 일괄 수정
    df_bk = load_sheet_cached('bookings')
    col_key = 'lab' if target_type == 'lab' else 'equipment'
    if not df_bk.empty and col_key in df_bk.columns:
        if old_name in df_bk[col_key].values:
            df_bk.loc[df_bk[col_key] == old_name, col_key] = new_name
            save_sheet('bookings', df_bk)
            
    # 4. 3차수(water) 일괄 수정 (실험실인 경우만)
    if target_type == 'lab':
        df_wt = load_sheet_cached('water')
        if not df_wt.empty and 'lab' in df_wt.columns:
            if old_name in df_wt['lab'].values:
                df_wt.loc[df_wt['lab'] == old_name, 'lab'] = new_name
                save_sheet('water', df_wt)
                
    return True, "변경 완료"

# ============================================================================
# 4. UI 구성
# ============================================================================

# 데이터 로드
df_labs = load_sheet_cached('labs')
df_eq = load_sheet_cached('equipment')

LABS = df_labs['name'].tolist() if not df_labs.empty else []
EQUIPMENT = df_eq['name'].tolist() if not df_eq.empty else []

if LABS: lab_scale = alt.Scale(domain=LABS, scheme='tableau20')
else: lab_scale = alt.Scale(scheme='tableau20')

st.title("🔬 실험실 공동 기기 예약 시스템 v3.0")

tab1, tab2, tab3, tab4 = st.tabs(["📅 예약관리", "📊 타임라인", "💧 3차수", "👮 관리자"])

# --- TAB 1: 예약관리 (예약하기 + 내 예약 수정/삭제) ---
with tab1:
    if not LABS or not EQUIPMENT:
        st.warning("⚠️ 초기 설정 필요: 관리자 탭에서 랩/기기를 등록하세요.")
    else:
        col1, col2 = st.columns([1, 1.2])
        
        # [왼쪽] 예약 하기
        with col1:
            st.subheader("📝 새 예약")
            with st.form("new_booking_form"):
                u_name = st.text_input("이름")
                u_lab = st.selectbox("실험실", LABS)
                u_date = st.date_input("날짜", datetime.now())
                u_eq = st.selectbox("기기", EQUIPMENT)
                
                c1, c2 = st.columns(2)
                u_start = c1.text_input("시작 (0900)", max_chars=4)
                u_end = c2.text_input("종료 (1800)", max_chars=4)
                u_pw = st.text_input("비밀번호 (4자리)", type="password", max_chars=4)
                
                submitted = st.form_submit_button("예약 등록", use_container_width=True)
                
                if submitted:
                    fs, fe = parse_time(u_start), parse_time(u_end)
                    if not u_name or len(u_pw) != 4: st.error("이름/비번 확인")
                    elif not fs or not fe: st.error("시간 형식 오류")
                    elif fs >= fe and fe != "24:00" and fs < "23:00": st.error("종료 시간이 시작보다 빠릅니다") 
                    else:
                        # 오버나이트 처리 로직 (단순화)
                        is_overnight = fe < fs
                        df_bk = load_sheet_cached('bookings')
                        
                        if is_overnight:
                            nd = u_date + timedelta(days=1)
                            ov1, u1 = check_overlap(df_bk, str(u_date), u_eq, fs, "24:00")
                            ov2, u2 = check_overlap(df_bk, str(nd), u_eq, "00:00", fe)
                            if ov1 or ov2: st.error(f"예약 충돌! ({u1 if ov1 else u2})")
                            else:
                                bid = datetime.now().strftime('%Y%m%d%H%M%S')
                                new_rows = pd.DataFrame([
                                    {'id': f"{bid}_1", 'user_name': u_name, 'lab': u_lab, 'equipment': u_eq, 'date': str(u_date), 'start_time': fs, 'end_time': "24:00", 'password': u_pw},
                                    {'id': f"{bid}_2", 'user_name': u_name, 'lab': u_lab, 'equipment': u_eq, 'date': str(nd), 'start_time': "00:00", 'end_time': fe, 'password': u_pw}
                                ])
                                df_bk = pd.concat([df_bk, new_rows], ignore_index=True)
                                if save_sheet('bookings', df_bk):
                                    add_log("예약(OV)", u_name, u_eq)
                                    st.success("예약 완료!"); st.rerun()
                        else:
                            ov, usr = check_overlap(df_bk, str(u_date), u_eq, fs, fe)
                            if ov: st.error(f"예약 충돌! ({usr})")
                            else:
                                new_row = pd.DataFrame([{
                                    'id': datetime.now().strftime('%Y%m%d%H%M%S'), 'user_name': u_name, 'lab': u_lab, 
                                    'equipment': u_eq, 'date': str(u_date), 'start_time': fs, 'end_time': fe, 'password': u_pw
                                }])
                                df_bk = pd.concat([df_bk, new_row], ignore_index=True)
                                if save_sheet('bookings', df_bk):
                                    add_log("예약", u_name, u_eq)
                                    st.success("예약 완료!"); st.rerun()

        # [오른쪽] 내 예약 관리 (수정/삭제)
        with col2:
            st.subheader("🔧 내 예약 관리")
            st.info("비밀번호 입력 후 수정/삭제 가능")
            
            my_pw = st.text_input("내 비밀번호 확인", type="password", key="my_mgmt_pw")
            df_bk = load_sheet_cached('bookings')
            
            if my_pw:
                # 비밀번호 일치하는 예약만 필터링
                my_bookings = df_bk[df_bk['password'] == my_pw].copy()
                
                # 미래 예약만 보여주기
                now_dt = datetime.now()
                valid_bookings = []
                for _, r in my_bookings.iterrows():
                    try:
                        end_t = "23:59" if r['end_time'] == "24:00" else r['end_time'][:5]
                        r_dt = datetime.strptime(f"{r['date']} {end_t}", "%Y-%m-%d %H:%M")
                        if r_dt >= now_dt: valid_bookings.append(r)
                    except: continue
                
                if valid_bookings:
                    for b in sorted(valid_bookings, key=lambda x: (x['date'], x['start_time'])):
                        with st.expander(f"📅 {b['date']} | {b['user_name']} | {b['equipment']}"):
                            c1, c2 = st.columns(2)
                            new_date = c1.date_input("날짜", datetime.strptime(b['date'], "%Y-%m-%d"), key=f"d_{b['id']}")
                            new_eq = c2.selectbox("기기", EQUIPMENT, index=EQUIPMENT.index(b['equipment']) if b['equipment'] in EQUIPMENT else 0, key=f"e_{b['id']}")
                            
                            c3, c4 = st.columns(2)
                            # 기존 시간 표시 (0900 형태로 변환)
                            st_val = b['start_time'].replace(":","")
                            et_val = b['end_time'].replace(":","")
                            new_start = c3.text_input("시작", value=st_val, max_chars=4, key=f"s_{b['id']}")
                            new_end = c4.text_input("종료", value=et_val, max_chars=4, key=f"en_{b['id']}")
                            
                            btn_c1, btn_c2 = st.columns(2)
                            
                            # [수정 기능]
                            if btn_c1.button("수정 저장", key=f"up_{b['id']}"):
                                nfs, nfe = parse_time(new_start), parse_time(new_end)
                                if not nfs or not nfe: st.error("시간 형식 오류")
                                else:
                                    # 중복 체크 (내 ID 제외하고 체크)
                                    ov, ur = check_overlap(df_bk, str(new_date), new_eq, nfs, nfe, exclude_id=b['id'])
                                    if ov: st.error(f"충돌! ({ur})")
                                    else:
                                        # 데이터 수정
                                        df_bk.loc[df_bk['id'] == b['id'], ['date', 'equipment', 'start_time', 'end_time']] = [str(new_date), new_eq, nfs, nfe]
                                        if save_sheet('bookings', df_bk):
                                            add_log("수정", b['user_name'], f"{b['id']}")
                                            st.success("수정 완료!"); st.rerun()
                            
                            # [삭제 기능]
                            if btn_c2.button("삭제", key=f"rm_{b['id']}"):
                                df_new = df_bk[df_bk['id'] != b['id']]
                                if save_sheet('bookings', df_new):
                                    add_log("삭제", b['user_name'], f"{b['id']}")
                                    st.success("삭제 완료!"); st.rerun()
                else:
                    st.info("예약 내역이 없습니다.")

# --- TAB 2: 타임라인 ---
with tab2:
    st.subheader("🕐 기기별 현황")
    td = st.date_input("조회 날짜", datetime.now(), key="t2_d")
    df_bk = load_sheet_cached('bookings')
    df_d = df_bk[df_bk['date'] == str(td)].copy()
    
    if not df_d.empty:
        df_d['start'] = pd.to_datetime(df_d['date'] + ' ' + df_d['start_time'].str[:5], format='%Y-%m-%d %H:%M')
        df_d['end'] = pd.to_datetime(df_d['date'] + ' ' + df_d['end_time'].str[:5].replace("24:00","23:59"), format='%Y-%m-%d %H:%M')
        
        ch = alt.Chart(df_d).mark_bar().encode(
            x=alt.X('start:T', scale=alt.Scale(domain=[pd.to_datetime(f"{td} 00:00"), pd.to_datetime(f"{td} 23:59")]), title='시간'),
            x2='end:T', y='equipment', color=alt.Color('lab', scale=lab_scale), tooltip=['user_name', 'lab', 'start_time', 'end_time']
        ).properties(height=400)
        st.altair_chart(ch, use_container_width=True)
    else: st.info("예약 없음")

# --- TAB 3: 3차수 ---
with tab3:
    c1, c2 = st.columns([1, 1.5])
    with c1:
        st.subheader("💧 사용량 기록")
        with st.form("wf"):
            wn = st.text_input("이름")
            wl = st.selectbox("실험실", LABS) if LABS else None
            wa = st.number_input("사용량 (L)", min_value=0.1, step=0.5)
            if st.form_submit_button("저장") and wn:
                df_w = load_sheet_cached('water')
                new_w = pd.DataFrame([{'date': datetime.now().strftime('%Y-%m-%d'), 'user_name': wn, 'lab': wl, 'amount': str(wa)}])
                df_w = pd.concat([df_w, new_w], ignore_index=True)
                if save_sheet('water', df_w):
                    add_log("3차수", wn, f"{wa}L")
                    st.success("저장됨"); st.rerun()
        st.dataframe(load_sheet_cached('water').tail(5), use_container_width=True, hide_index=True)
    
    with c2:
        st.subheader("📊 통계")
        df_w = load_sheet_cached('water')
        if not df_w.empty:
            df_w['amount'] = pd.to_numeric(df_w['amount'], errors='coerce')
            cm = datetime.now().strftime('%Y-%m')
            df_w['mon'] = pd.to_datetime(df_w['date']).dt.strftime('%Y-%m')
            
            st.markdown(f"**이번 달 ({cm})**")
            df_m = df_w[df_w['mon'] == cm]
            if not df_m.empty:
                base = alt.Chart(df_m).encode(theta=alt.Theta("amount", stack=True))
                pie = base.mark_arc(innerRadius=60).encode(color=alt.Color("lab", scale=lab_scale), tooltip=['lab', 'amount'])
                st.altair_chart(pie, use_container_width=True)
            else: st.info("데이터 없음")

# --- TAB 4: 관리자 ---
with tab4:
    st.subheader("👮 관리자 페이지")
    apw = st.text_input("관리자 비밀번호", type="password", key="adm_pw")
    if apw == ADMIN_PASSWORD:
        st.success("접속 승인")
        at1, at2, at3 = st.tabs(["⚙️ 데이터 관리", "📅 예약 데이터", "📜 로그"])
        
        with at1:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### 🧪 실험실 관리")
                d_lab = st.data_editor(load_sheet_cached('labs'), num_rows="dynamic", key="ed_lab", hide_index=True)
                if st.button("저장", key="sv_lab"):
                    save_sheet('labs', d_lab); st.rerun()
                
                with st.expander("🔄 이름 변경 (데이터 일괄 업데이트)"):
                    if LABS:
                        old_l = st.selectbox("변경 전", LABS, key="ol")
                        new_l = st.text_input("변경 후", key="nl")
                        if st.button("변경 적용", key="bl"):
                            suc, msg = batch_update_name('lab', old_l, new_l)
                            if suc: st.success(msg); st.rerun()
                            else: st.error(msg)

            with c2:
                st.markdown("#### 🔬 기기 관리")
                d_eq = st.data_editor(load_sheet_cached('equipment'), num_rows="dynamic", key="ed_eq", hide_index=True)
                if st.button("저장", key="sv_eq"):
                    save_sheet('equipment', d_eq); st.rerun()
                
                with st.expander("🔄 이름 변경 (데이터 일괄 업데이트)"):
                    if EQUIPMENT:
                        old_e = st.selectbox("변경 전", EQUIPMENT, key="oe")
                        new_e = st.text_input("변경 후", key="ne")
                        if st.button("변경 적용", key="be"):
                            suc, msg = batch_update_name('equipment', old_e, new_e)
                            if suc: st.success(msg); st.rerun()
                            else: st.error(msg)

        with at2:
            st.warning("⚠️ 예약 데이터 직접 수정")
            d_bk = st.data_editor(load_sheet_cached('bookings'), num_rows="dynamic", key="ed_bk", hide_index=True)
            if st.button("예약 전체 저장"): save_sheet('bookings', d_bk); st.success("완료")

        with at3:
            try:
                st.dataframe(load_sheet_cached('logs').sort_values(by='timestamp', ascending=False), use_container_width=True, hide_index=True)
            except: st.info("로그 없음")